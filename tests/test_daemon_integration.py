from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic_ai import Agent, DeferredToolRequests, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from lattis.agents.plugin import AgentPlugin, AgentRunContext, PluginStateContext
from lattis.agents.registry import AgentRegistry
from lattis.client.inprocess import create_inprocess_client
from lattis.protocol.schemas import (
    ItemDeltaEvent,
    PluginStateUpdatedEvent,
    RunCompletedEvent,
    RunWaitingApprovalEvent,
)
from lattis.server.app import create_app
from lattis.settings.storage import load_daemon_config


@dataclass
class _DemoDeps:
    ctx: AgentRunContext


def _build_echo_plugin() -> AgentPlugin:
    async def stream_model(messages: list[ModelMessage], info: AgentInfo):
        yield "Hello "
        yield "from Lattis!"

    def create_agent(_model: str) -> Agent[None, str]:
        return Agent(FunctionModel(stream_function=stream_model), deps_type=None)

    return AgentPlugin(
        id="echo",
        name="Echo",
        create_agent=create_agent,
        default_model="test-echo",
        list_models=lambda: ["test-echo", "test-echo-v2"],
        validate_model=lambda m: None if m.startswith("test-") else (_ for _ in ()).throw(ValueError("invalid model")),
    )


def _build_tool_plugin(*, slow_seconds: float = 0.0) -> AgentPlugin:
    async def stream_model(messages: list[ModelMessage], info: AgentInfo):
        # If tool already returned, emit final text
        last = messages[-1]
        if any(getattr(p, "part_kind", "") == "tool-return" for p in last.parts):
            yield "Tool finished."
            return
        yield {0: DeltaToolCall(name="run_job", json_args='{"label": "build"}', tool_call_id="tc-1")}

    def create_agent(_model: str) -> Agent[_DemoDeps, str]:
        agent: Agent[_DemoDeps, str] = Agent(
            FunctionModel(stream_function=stream_model),
            deps_type=_DemoDeps,
        )

        @agent.tool
        async def run_job(ctx: RunContext[_DemoDeps], label: str) -> dict[str, Any]:
            if ctx.tool_call_id:
                ctx.deps.ctx.emit_tool_output(ctx.tool_call_id, f"starting {label}\n", "stdout")
            if slow_seconds > 0:
                await asyncio.sleep(slow_seconds)
            if ctx.tool_call_id:
                ctx.deps.ctx.emit_tool_output(ctx.tool_call_id, "done\n", "stdout")
            ctx.deps.ctx.notify_state_changed()
            return {"exit_code": 0, "stdout": f"ok:{label}"}

        return agent

    def get_state(sctx: PluginStateContext) -> dict[str, Any]:
        return {"project_root": str(sctx.project_root), "ready": True}

    return AgentPlugin(
        id="worker",
        name="Worker",
        create_agent=create_agent,
        create_deps=lambda rctx: _DemoDeps(ctx=rctx),
        get_state=get_state,
        default_model="test-worker",
        list_models=lambda: ["test-worker"],
        validate_model=lambda _m: None,
    )


def _build_approval_plugin() -> AgentPlugin:
    async def stream_model(messages: list[ModelMessage], info: AgentInfo):
        last = messages[-1]
        if any(getattr(p, "part_kind", "") == "tool-return" for p in last.parts):
            yield "Approved action complete."
            return
        yield {0: DeltaToolCall(name="danger_op", json_args='{"target": "prod"}', tool_call_id="tc-apr-1")}

    def create_agent(_model: str) -> Agent[None, str | DeferredToolRequests]:
        agent: Agent[None, str | DeferredToolRequests] = Agent(
            FunctionModel(stream_function=stream_model),
            output_type=[str, DeferredToolRequests],
        )

        @agent.tool_plain(requires_approval=True)
        def danger_op(target: str) -> str:
            return f"executed:{target}"

        return agent

    return AgentPlugin(
        id="approver",
        name="Approver",
        create_agent=create_agent,
        default_model="test-apr",
        list_models=lambda: ["test-apr"],
        validate_model=lambda _m: None,
    )


def test_auth_enforcement_and_cors(tmp_path: Path) -> None:
    async def _run() -> None:
        registry = AgentRegistry(agents={"echo": _build_echo_plugin()}, default_agent="echo")
        client, daemon = create_inprocess_client(
            home_dir=tmp_path / "home",
            registry=registry,
            cors_origins=("http://localhost:5173",),
        )
        try:
            # Unauthenticated /health succeeds
            unauth = httpx.AsyncClient(base_url="http://lattis.inprocess", transport=httpx.ASGITransport(app=daemon.app))
            r_health = await unauth.get("/health")
            assert r_health.status_code == 200

            # Protected route rejects missing or wrong token
            assert (await unauth.get("/workspaces")).status_code == 401
            assert (
                await unauth.get("/workspaces", headers={"Authorization": "Bearer wrong"})
            ).status_code == 401

            # Query token works (for browser EventSource SSE)
            r_query = await unauth.get(f"/info?token={daemon.auth_token}")
            assert r_query.status_code == 200

            # Strict CORS allows configured origin and omits wildcard for unknown origin
            r_cors_ok = await unauth.options(
                "/workspaces",
                headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
            )
            assert r_cors_ok.headers.get("access-control-allow-origin") == "http://localhost:5173"

            r_cors_bad = await unauth.options(
                "/workspaces",
                headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
            )
            assert r_cors_bad.headers.get("access-control-allow-origin") is None
            await unauth.aclose()
        finally:
            await client.close()
            await daemon.aclose()

    asyncio.run(_run())


def test_full_run_streaming_items_and_plugin_state(tmp_path: Path) -> None:
    async def _run() -> None:
        registry = AgentRegistry(
            agents={"echo": _build_echo_plugin(), "worker": _build_tool_plugin()},
            default_agent="worker",
        )
        client, daemon = create_inprocess_client(home_dir=tmp_path / "home", registry=registry)
        try:
            proj = tmp_path / "my-repo"
            proj.mkdir()
            ws = await client.register_workspace(str(proj))
            assert ws.name == "my-repo"

            thread = await client.create_thread(ws.id)
            assert thread.resolved_agent.agent == "worker"
            assert thread.resolved_model.model == "test-worker"

            # Subscribe directly on the EventBus (simulating concurrent GUI listener)
            collected = []

            async def listen() -> None:
                async for ev in daemon.ctx.bus.subscribe(workspace_id=ws.id):
                    collected.append(ev)
                    if isinstance(ev, RunCompletedEvent):
                        break

            listener = asyncio.create_task(listen())
            await asyncio.sleep(0.01)

            created = await client.start_run(thread.id, "Please run the build job")
            assert created.run.status == "running"
            assert created.user_item.kind == "user_message"

            await asyncio.wait_for(listener, timeout=5.0)

            # Verify auto-title, persisted items, live tool_output deltas, and plugin state update
            refreshed = await client.get_thread(thread.id)
            assert refreshed.title == "Please run the build job"
            assert refreshed.status == "idle"

            items = (await client.list_thread_items(thread.id)).items
            kinds = [item.kind for item in items]
            assert kinds == ["user_message", "tool_call", "assistant_text"]
            assert items[1].payload["result"] == {"exit_code": 0, "stdout": "ok:build"}
            assert "starting build" in items[1].payload["output_stream"]
            assert items[2].payload["text"] == "Tool finished."

            tool_output_deltas = [
                ev for ev in collected if isinstance(ev, ItemDeltaEvent) and ev.data.channel == "tool_output"
            ]
            assert len(tool_output_deltas) >= 2
            assert any(isinstance(ev, PluginStateUpdatedEvent) for ev in collected)

            # REST plugin state endpoint matches
            pstate = await client.get_plugin_state(ws.id, "worker")
            assert pstate.state == {"project_root": str(proj.resolve()), "ready": True}
        finally:
            await client.close()
            await daemon.aclose()

    asyncio.run(_run())


def test_run_cancellation_and_busy_guard(tmp_path: Path) -> None:
    async def _run() -> None:
        registry = AgentRegistry(
            agents={"worker": _build_tool_plugin(slow_seconds=5.0)},
            default_agent="worker",
        )
        client, daemon = create_inprocess_client(home_dir=tmp_path / "home", registry=registry)
        try:
            thread = await client.create_thread("global")
            started = await client.start_run(thread.id, "long task")

            # Second concurrent run on same thread returns 409
            try:
                await client.start_run(thread.id, "second task")
                assert False, "Expected 409 conflict"
            except RuntimeError as exc:
                assert "already has an active run" in str(exc)

            await asyncio.sleep(0.05)
            cancelled = await client.cancel_run(started.run.id)
            assert cancelled.status == "cancelled"

            refreshed = await client.get_thread(thread.id)
            assert refreshed.status == "idle"
            assert refreshed.active_run_id is None
        finally:
            await client.close()
            await daemon.aclose()

    asyncio.run(_run())


def test_deferred_tool_approval_pause_and_resume(tmp_path: Path) -> None:
    async def _run() -> None:
        registry = AgentRegistry(
            agents={"approver": _build_approval_plugin()},
            default_agent="approver",
        )
        client, daemon = create_inprocess_client(home_dir=tmp_path / "home", registry=registry)
        try:
            thread = await client.create_thread("global")

            waiting_ev_future: asyncio.Future[RunWaitingApprovalEvent] = asyncio.get_running_loop().create_future()
            completed_ev_future: asyncio.Future[RunCompletedEvent] = asyncio.get_running_loop().create_future()

            async def listen() -> None:
                async for ev in daemon.ctx.bus.subscribe(thread_id=thread.id):
                    if isinstance(ev, RunWaitingApprovalEvent) and not waiting_ev_future.done():
                        waiting_ev_future.set_result(ev)
                    if isinstance(ev, RunCompletedEvent) and not completed_ev_future.done():
                        completed_ev_future.set_result(ev)
                        break

            listener = asyncio.create_task(listen())
            await asyncio.sleep(0.01)

            created = await client.start_run(thread.id, "deploy to prod")
            waiting = await asyncio.wait_for(waiting_ev_future, timeout=5.0)
            assert waiting.data.run.status == "waiting_approval"
            assert len(waiting.data.approval_items) == 1
            approval_id = waiting.data.approval_items[0].payload["approval_id"]

            resolved = await client.resolve_approval(
                created.run.id,
                approval_id,
                approved=True,
            )
            assert resolved.approval_item.payload["decision"] == "approved"

            done = await asyncio.wait_for(completed_ev_future, timeout=5.0)
            await listener
            assert done.data.status == "completed"

            items = (await client.list_thread_items(thread.id)).items
            assistant_texts = [i.payload["text"] for i in items if i.kind == "assistant_text"]
            assert "Approved action complete." in assistant_texts
        finally:
            await client.close()
            await daemon.aclose()

    asyncio.run(_run())


def test_openapi_exports_event_union(tmp_path: Path) -> None:
    config = load_daemon_config(home_dir=tmp_path / "home", auth_disabled=True)
    app = create_app(config=config)
    schema = app.openapi()
    schemas = schema["components"]["schemas"]
    assert "EventSchemaEnvelope" in schemas
    assert "ItemDeltaEvent" in schemas
    assert "RunWaitingApprovalEvent" in schemas
    assert "PluginStateUpdatedEvent" in schemas
    # Verify JSON-serializable
    json.dumps(schema)

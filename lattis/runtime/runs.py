from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults, ToolApproved, ToolDenied
from pydantic_ai.messages import (
    BuiltinToolCallEvent,
    BuiltinToolCallPart,
    BuiltinToolResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolCallPartDelta,
)
from pydantic_ai.run import AgentRunResultEvent

from lattis.agents.plugin import AgentPlugin, AgentRunContext, PluginStateContext
from lattis.agents.registry import AgentRegistry
from lattis.domain.agents import select_agent_for_thread
from lattis.domain.errors import (
    ApprovalNotFoundError,
    RunNotFoundError,
    ThreadBusyError,
    ThreadNotFoundError,
    WorkspaceNotFoundError,
)
from lattis.domain.model_selection import select_thread_model
from lattis.domain.models import (
    DaemonStore,
    ItemRecord,
    RunRecord,
    ThreadRecord,
    WorkspaceRecord,
    generate_approval_id,
    generate_run_id,
)
from lattis.protocol.schemas import (
    ItemCompletedEvent,
    ItemCreatedEvent,
    ItemDeltaData,
    ItemDeltaEvent,
    ItemResponse,
    PluginStateResponse,
    PluginStateUpdatedEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunResponse,
    RunStartedEvent,
    RunWaitingApprovalData,
    RunWaitingApprovalEvent,
    ThreadAgentResponse,
    ThreadModelResponse,
    ThreadResponse,
    ThreadUpdatedEvent,
)
from lattis.runtime.events import EventBus
from lattis.settings.storage import DaemonConfig

logger = logging.getLogger(__name__)


def _auto_title(text: str, *, max_len: int = 60) -> str:
    first_line = " ".join(text.strip().splitlines()[:1]).strip()
    if len(first_line) <= max_len:
        return first_line
    return first_line[: max_len - 1].rstrip() + "…"


def _extract_usage(usage: Any) -> dict[str, Any] | None:
    if usage is None:
        return None
    out: dict[str, Any] = {}
    for attr in (
        "requests",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
    ):
        value = getattr(usage, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                continue
        if isinstance(value, (int, float)):
            out[attr] = value
    return out or None


def _serialize_tool_result(content: Any) -> Any:
    if content is None or isinstance(content, (str, int, float, bool, list, dict)):
        return content
    if hasattr(content, "model_dump"):
        try:
            return content.model_dump(mode="json")
        except Exception:
            pass
    return str(content)


def _parse_tool_args(args: Any) -> Any:
    if args is None:
        return {}
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        stripped = args.strip()
        if not stripped:
            return {}
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return args
    return str(args)


@dataclass
class _PendingApprovalState:
    run_id: str
    thread_id: str
    workspace_id: str
    agent_id: str
    model: str
    approvals_by_id: dict[str, tuple[str, str]]  # approval_id -> (tool_call_id, item_id)
    decisions: dict[str, ToolApproved | ToolDenied] = field(default_factory=dict)


@dataclass
class _ActiveRun:
    run_id: str
    thread_id: str
    workspace_id: str
    task: asyncio.Task[None] | None = None
    tool_items: dict[str, ItemRecord] = field(default_factory=dict)
    tool_buffers: dict[str, str] = field(default_factory=dict)
    part_items: dict[int, tuple[ItemRecord, str]] = field(default_factory=dict)  # part_index -> (item, buf)
    pending_approval: _PendingApprovalState | None = None


class RunManager:
    """Owns background agent execution, per-thread locks, cancellation, and approvals."""

    def __init__(
        self,
        *,
        config: DaemonConfig,
        store: DaemonStore,
        registry: AgentRegistry,
        bus: EventBus,
    ) -> None:
        self._config = config
        self._store = store
        self._registry = registry
        self._bus = bus
        self._thread_locks: dict[str, asyncio.Lock] = {}
        self._active_by_thread: dict[str, _ActiveRun] = {}
        self._active_by_run: dict[str, _ActiveRun] = {}

    def _lock_for_thread(self, thread_id: str) -> asyncio.Lock:
        lock = self._thread_locks.get(thread_id)
        if lock is None:
            lock = asyncio.Lock()
            self._thread_locks[thread_id] = lock
        return lock

    @property
    def active_run_count(self) -> int:
        return len(self._active_by_run)

    def get_active_run_id(self, thread_id: str) -> str | None:
        active = self._active_by_thread.get(thread_id)
        return active.run_id if active else None

    def build_thread_response(
        self,
        thread: ThreadRecord,
        *,
        workspace: WorkspaceRecord | None = None,
    ) -> ThreadResponse:
        ws = workspace or self._store.get_workspace(thread.workspace_id)
        agent_sel = select_agent_for_thread(self._registry, thread, workspace=ws)
        model_sel = select_thread_model(self._store, thread, plugin=agent_sel.plugin, workspace=ws)
        return ThreadResponse.from_record(
            thread,
            resolved_agent=ThreadAgentResponse(
                agent=agent_sel.agent_id,
                default_agent=agent_sel.default_agent_id,
                is_default=agent_sel.is_default,
                agent_name=agent_sel.agent_name,
            ),
            resolved_model=ThreadModelResponse(
                model=model_sel.model,
                default_model=model_sel.default_model,
                is_default=model_sel.is_default,
            ),
            active_run_id=self.get_active_run_id(thread.id),
        )

    async def start_run(self, *, thread_id: str, user_input: str) -> tuple[RunRecord, ItemRecord]:
        lock = self._lock_for_thread(thread_id)
        async with lock:
            thread = self._store.get_thread(thread_id)
            if thread is None:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
            if thread_id in self._active_by_thread:
                raise ThreadBusyError(f"Thread '{thread_id}' already has an active run.")

            workspace = self._store.get_workspace(thread.workspace_id)
            if workspace is None:
                raise WorkspaceNotFoundError(f"Workspace '{thread.workspace_id}' not found.")

            agent_sel = select_agent_for_thread(self._registry, thread, workspace=workspace)
            model_sel = select_thread_model(self._store, thread, plugin=agent_sel.plugin, workspace=workspace)

            run_id = generate_run_id()
            run = self._store.create_run(
                run_id=run_id,
                thread_id=thread.id,
                workspace_id=workspace.id,
                agent_id=agent_sel.agent_id,
                model=model_sel.model,
                status="running",
            )

            user_item = self._store.append_item(
                thread_id=thread.id,
                run_id=run.id,
                kind="user_message",
                status="completed",
                payload={"text": user_input},
            )

            new_title = _auto_title(user_input) if not thread.title else None
            updated_thread = self._store.update_thread(
                thread.id,
                title=new_title,
                status="running",
            )

            active = _ActiveRun(run_id=run.id, thread_id=thread.id, workspace_id=workspace.id)
            self._active_by_thread[thread.id] = active
            self._active_by_run[run.id] = active

            self._bus.publish(
                ItemCreatedEvent,
                data=ItemResponse.from_record(user_item),
                workspace_id=workspace.id,
                thread_id=thread.id,
                run_id=run.id,
            )
            self._bus.publish(
                ThreadUpdatedEvent,
                data=self.build_thread_response(updated_thread, workspace=workspace),
                workspace_id=workspace.id,
                thread_id=thread.id,
                run_id=run.id,
            )
            self._bus.publish(
                RunStartedEvent,
                data=RunResponse.from_record(run),
                workspace_id=workspace.id,
                thread_id=thread.id,
                run_id=run.id,
            )

            active.task = asyncio.create_task(
                self._execute_run(
                    active=active,
                    workspace=workspace,
                    plugin=agent_sel.plugin,
                    model_name=model_sel.model,
                    user_prompt=user_input,
                    deferred_tool_results=None,
                ),
                name=f"lattis-run-{run.id}",
            )
            return run, user_item

    async def cancel_run(self, run_id: str) -> RunRecord:
        active = self._active_by_run.get(run_id)
        if active is None:
            run = self._store.get_run(run_id)
            if run is None:
                raise RunNotFoundError(f"Run '{run_id}' not found.")
            return run

        if active.task is not None and not active.task.done():
            active.task.cancel()
            try:
                await active.task
            except asyncio.CancelledError:
                pass
        else:
            # Waiting for approval with no active task: cancel directly
            await self._finalize_cancelled(active)

        updated = self._store.get_run(run_id)
        if updated is None:
            raise RunNotFoundError(f"Run '{run_id}' not found.")
        return updated

    async def cancel_thread_run(self, thread_id: str) -> None:
        active = self._active_by_thread.get(thread_id)
        if active is not None:
            await self.cancel_run(active.run_id)

    async def resolve_approval(
        self,
        *,
        run_id: str,
        approval_id: str,
        approved: bool,
        reason: str | None = None,
    ) -> tuple[RunRecord, ItemRecord]:
        active = self._active_by_run.get(run_id)
        if active is None or active.pending_approval is None:
            raise ApprovalNotFoundError(f"No pending approval '{approval_id}' for run '{run_id}'.")

        pending = active.pending_approval
        entry = pending.approvals_by_id.get(approval_id)
        if entry is None:
            raise ApprovalNotFoundError(f"Approval '{approval_id}' not found on run '{run_id}'.")

        tool_call_id, item_id = entry
        item = self._store.get_item(item_id)
        if item is None:
            raise ApprovalNotFoundError(f"Approval item '{item_id}' not found.")

        decision_str = "approved" if approved else "denied"
        updated_payload = {
            **item.payload,
            "decision": decision_str,
            "reason": reason,
        }
        updated_item = self._store.update_item(item_id, status="completed", payload=updated_payload)
        self._bus.publish(
            ItemCompletedEvent,
            data=ItemResponse.from_record(updated_item),
            workspace_id=active.workspace_id,
            thread_id=active.thread_id,
            run_id=active.run_id,
        )

        if approved:
            pending.decisions[tool_call_id] = ToolApproved()
        else:
            pending.decisions[tool_call_id] = ToolDenied(reason or "Denied by user.")

        # If all approvals for this run are decided, resume execution
        if len(pending.decisions) >= len(pending.approvals_by_id):
            decisions = dict(pending.decisions)
            active.pending_approval = None
            workspace = self._store.get_workspace(active.workspace_id)
            if workspace is None:
                raise WorkspaceNotFoundError(f"Workspace '{active.workspace_id}' not found.")
            plugin = self._registry.get(pending.agent_id)
            if plugin is None:
                raise RuntimeError(f"Agent '{pending.agent_id}' is no longer registered.")

            run = self._store.update_run(run_id, status="running")
            thread = self._store.update_thread(active.thread_id, status="running")
            self._bus.publish(
                ThreadUpdatedEvent,
                data=self.build_thread_response(thread, workspace=workspace),
                workspace_id=workspace.id,
                thread_id=thread.id,
                run_id=run.id,
            )
            self._bus.publish(
                RunStartedEvent,
                data=RunResponse.from_record(run),
                workspace_id=workspace.id,
                thread_id=thread.id,
                run_id=run.id,
            )
            active.task = asyncio.create_task(
                self._execute_run(
                    active=active,
                    workspace=workspace,
                    plugin=plugin,
                    model_name=pending.model,
                    user_prompt=None,
                    deferred_tool_results=DeferredToolResults(approvals=decisions),
                ),
                name=f"lattis-run-{run.id}-resume",
            )
            return run, updated_item

        run = self._store.get_run(run_id)
        assert run is not None
        return run, updated_item

    async def shutdown(self) -> None:
        actives = list(self._active_by_run.values())
        for active in actives:
            if active.task is not None and not active.task.done():
                active.task.cancel()
        for active in actives:
            if active.task is not None:
                try:
                    await active.task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            elif active.pending_approval is not None:
                await self._finalize_cancelled(active)

    # ------------------------------------------------------------------
    # Internal run execution
    # ------------------------------------------------------------------

    def _make_run_context(
        self,
        *,
        active: _ActiveRun,
        workspace: WorkspaceRecord,
        plugin: AgentPlugin,
        model_name: str,
    ) -> AgentRunContext:
        loop = asyncio.get_running_loop()

        def emit_tool_output(tool_call_id: str, chunk: str, stream: str = "stdout") -> None:
            if not chunk:
                return
            item = active.tool_items.get(tool_call_id)
            if item is None:
                return
            buf = active.tool_buffers.get(tool_call_id, "")
            active.tool_buffers[tool_call_id] = buf + chunk
            stream_val = "stderr" if stream == "stderr" else "stdout"
            self._bus.publish(
                ItemDeltaEvent,
                data=ItemDeltaData(
                    item_id=item.id,
                    channel="tool_output",
                    delta=chunk,
                    stream=stream_val,
                ),
                workspace_id=workspace.id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )

        def notify_state_changed() -> None:
            if plugin.get_state is None:
                return
            loop.create_task(self.publish_plugin_state(workspace=workspace, plugin=plugin))

        return AgentRunContext(
            workspace_id=workspace.id,
            thread_id=active.thread_id,
            run_id=active.run_id,
            model=model_name,
            project_root=Path(workspace.root_path),
            plugin_data_dir=self._config.plugin_data_dir(plugin.id),
            workspace_data_dir=self._config.workspace_data_dir(workspace.id, plugin.id),
            emit_tool_output=emit_tool_output,
            notify_state_changed=notify_state_changed,
        )

    async def publish_plugin_state(
        self,
        *,
        workspace: WorkspaceRecord,
        plugin: AgentPlugin,
    ) -> dict[str, Any] | None:
        if plugin.get_state is None:
            return None
        state_ctx = PluginStateContext(
            workspace_id=workspace.id,
            project_root=Path(workspace.root_path),
            plugin_data_dir=self._config.plugin_data_dir(plugin.id),
            workspace_data_dir=self._config.workspace_data_dir(workspace.id, plugin.id),
        )
        try:
            raw = plugin.get_state(state_ctx)
            state = await raw if inspect.isawaitable(raw) else raw
        except Exception as exc:
            logger.warning("Plugin '%s' get_state failed: %s", plugin.id, exc)
            return None
        self._bus.publish(
            PluginStateUpdatedEvent,
            data=PluginStateResponse(
                workspace_id=workspace.id,
                agent_id=plugin.id,
                state=state,
            ),
            workspace_id=workspace.id,
        )
        return state

    async def _execute_run(
        self,
        *,
        active: _ActiveRun,
        workspace: WorkspaceRecord,
        plugin: AgentPlugin,
        model_name: str,
        user_prompt: str | None,
        deferred_tool_results: DeferredToolResults | None,
    ) -> None:
        try:
            agent = plugin.create_agent(model_name)
            run_ctx = self._make_run_context(
                active=active,
                workspace=workspace,
                plugin=plugin,
                model_name=model_name,
            )
            deps = plugin.create_deps(run_ctx) if plugin.create_deps else None
            history: list[ModelMessage] = self._store.load_model_messages(active.thread_id)

            final_result: Any = None
            async for event in agent.run_stream_events(
                user_prompt,
                message_history=history,
                deps=deps,
                deferred_tool_results=deferred_tool_results,
            ):
                if isinstance(event, PartStartEvent):
                    self._handle_part_start(active, event)
                elif isinstance(event, PartDeltaEvent):
                    self._handle_part_delta(active, event)
                elif isinstance(event, PartEndEvent):
                    self._handle_part_end(active, event)
                elif isinstance(event, (FunctionToolCallEvent, BuiltinToolCallEvent)):
                    self._handle_tool_call_ready(active, event.part)
                elif isinstance(event, (FunctionToolResultEvent, BuiltinToolResultEvent)):
                    self._handle_tool_result(active, event.result)
                elif isinstance(event, AgentRunResultEvent):
                    final_result = event.result

            if final_result is not None:
                all_messages = final_result.all_messages()
                self._store.save_model_messages(active.thread_id, all_messages)

                # Check if agent paused for tool approvals
                if isinstance(getattr(final_result, "output", None), DeferredToolRequests):
                    deferred: DeferredToolRequests = final_result.output
                    await self._enter_waiting_approval(
                        active=active,
                        workspace=workspace,
                        plugin=plugin,
                        model_name=model_name,
                        deferred=deferred,
                    )
                    return

                if plugin.on_complete is not None:
                    maybe = plugin.on_complete(run_ctx, final_result)
                    if inspect.isawaitable(maybe):
                        await maybe

                usage = _extract_usage(final_result.usage())
            else:
                usage = None

            self._flush_open_parts(active, final_status="completed")
            finished_run = self._store.update_run(
                active.run_id,
                status="completed",
                usage=usage,
                ended_at=time.time(),
            )
            self._cleanup_active(active)
            updated_thread = self._store.update_thread(active.thread_id, status="idle")
            self._bus.publish(
                ThreadUpdatedEvent,
                data=self.build_thread_response(updated_thread, workspace=workspace),
                workspace_id=workspace.id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            self._bus.publish(
                RunCompletedEvent,
                data=RunResponse.from_record(finished_run),
                workspace_id=workspace.id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
        except asyncio.CancelledError:
            await self._finalize_cancelled(active)
            raise
        except Exception as exc:
            logger.exception("Run '%s' failed on thread '%s'", active.run_id, active.thread_id)
            self._flush_open_parts(active, final_status="error")
            failed_run = self._store.update_run(
                active.run_id,
                status="failed",
                error=str(exc),
                ended_at=time.time(),
            )
            self._cleanup_active(active)
            try:
                updated_thread = self._store.update_thread(active.thread_id, status="idle")
                self._bus.publish(
                    ThreadUpdatedEvent,
                    data=self.build_thread_response(updated_thread, workspace=workspace),
                    workspace_id=workspace.id,
                    thread_id=active.thread_id,
                    run_id=active.run_id,
                )
            except ThreadNotFoundError:
                pass
            self._bus.publish(
                RunFailedEvent,
                data=RunResponse.from_record(failed_run),
                workspace_id=workspace.id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )

    async def _enter_waiting_approval(
        self,
        *,
        active: _ActiveRun,
        workspace: WorkspaceRecord,
        plugin: AgentPlugin,
        model_name: str,
        deferred: DeferredToolRequests,
    ) -> None:
        deferred_ids = {call.tool_call_id for call in deferred.approvals}
        self._flush_open_parts(active, final_status="completed", skip_tool_call_ids=deferred_ids)
        approvals_by_id: dict[str, tuple[str, str]] = {}
        approval_items: list[ItemResponse] = []

        for call in deferred.approvals:
            approval_id = generate_approval_id()
            item = self._store.append_item(
                thread_id=active.thread_id,
                run_id=active.run_id,
                kind="approval_request",
                status="streaming",
                payload={
                    "approval_id": approval_id,
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "args": _parse_tool_args(call.args),
                    "decision": None,
                    "reason": None,
                },
            )
            approvals_by_id[approval_id] = (call.tool_call_id, item.id)
            item_resp = ItemResponse.from_record(item)
            approval_items.append(item_resp)
            self._bus.publish(
                ItemCreatedEvent,
                data=item_resp,
                workspace_id=workspace.id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )

        active.pending_approval = _PendingApprovalState(
            run_id=active.run_id,
            thread_id=active.thread_id,
            workspace_id=workspace.id,
            agent_id=plugin.id,
            model=model_name,
            approvals_by_id=approvals_by_id,
        )
        active.task = None

        waiting_run = self._store.update_run(active.run_id, status="waiting_approval")
        updated_thread = self._store.update_thread(active.thread_id, status="waiting_approval")
        self._bus.publish(
            ThreadUpdatedEvent,
            data=self.build_thread_response(updated_thread, workspace=workspace),
            workspace_id=workspace.id,
            thread_id=active.thread_id,
            run_id=active.run_id,
        )
        self._bus.publish(
            RunWaitingApprovalEvent,
            data=RunWaitingApprovalData(
                run=RunResponse.from_record(waiting_run),
                approval_items=approval_items,
            ),
            workspace_id=workspace.id,
            thread_id=active.thread_id,
            run_id=active.run_id,
        )

    async def _finalize_cancelled(self, active: _ActiveRun) -> None:
        self._flush_open_parts(active, final_status="cancelled")
        cancelled_run = self._store.update_run(
            active.run_id,
            status="cancelled",
            ended_at=time.time(),
        )
        self._cleanup_active(active)
        workspace = self._store.get_workspace(active.workspace_id)
        try:
            updated_thread = self._store.update_thread(active.thread_id, status="idle")
            if workspace is not None:
                self._bus.publish(
                    ThreadUpdatedEvent,
                    data=self.build_thread_response(updated_thread, workspace=workspace),
                    workspace_id=workspace.id,
                    thread_id=active.thread_id,
                    run_id=active.run_id,
                )
        except ThreadNotFoundError:
            pass
        self._bus.publish(
            RunCancelledEvent,
            data=RunResponse.from_record(cancelled_run),
            workspace_id=active.workspace_id,
            thread_id=active.thread_id,
            run_id=active.run_id,
        )

    def _cleanup_active(self, active: _ActiveRun) -> None:
        if self._active_by_thread.get(active.thread_id) is active:
            del self._active_by_thread[active.thread_id]
        if self._active_by_run.get(active.run_id) is active:
            del self._active_by_run[active.run_id]

    def _flush_open_parts(
        self,
        active: _ActiveRun,
        *,
        final_status: str,
        skip_tool_call_ids: set[str] | None = None,
    ) -> None:
        skip = skip_tool_call_ids or set()
        for idx in list(active.part_items.keys()):
            item, buf = active.part_items.pop(idx)
            if item.kind in {"assistant_text", "reasoning"}:
                updated = self._store.update_item(
                    item.id,
                    status=final_status,  # type: ignore[arg-type]
                    payload={"text": buf},
                )
                self._bus.publish(
                    ItemCompletedEvent,
                    data=ItemResponse.from_record(updated),
                    workspace_id=active.workspace_id,
                    thread_id=active.thread_id,
                    run_id=active.run_id,
                )
        for tool_call_id, item in list(active.tool_items.items()):
            if tool_call_id in skip:
                continue
            current = self._store.get_item(item.id)
            if current and current.status == "streaming":
                payload = {
                    **current.payload,
                    "output_stream": active.tool_buffers.get(tool_call_id, current.payload.get("output_stream", "")),
                }
                updated = self._store.update_item(
                    item.id,
                    status=final_status,  # type: ignore[arg-type]
                    payload=payload,
                )
                self._bus.publish(
                    ItemCompletedEvent,
                    data=ItemResponse.from_record(updated),
                    workspace_id=active.workspace_id,
                    thread_id=active.thread_id,
                    run_id=active.run_id,
                )

    # ------------------------------------------------------------------
    # Stream event handlers
    # ------------------------------------------------------------------

    def _handle_part_start(self, active: _ActiveRun, event: PartStartEvent) -> None:
        part = event.part
        if isinstance(part, TextPart):
            initial = part.content or ""
            item = self._store.append_item(
                thread_id=active.thread_id,
                run_id=active.run_id,
                kind="assistant_text",
                status="streaming",
                payload={"text": initial},
            )
            active.part_items[event.index] = (item, initial)
            self._bus.publish(
                ItemCreatedEvent,
                data=ItemResponse.from_record(item),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            return

        if isinstance(part, ThinkingPart):
            initial = part.content or ""
            item = self._store.append_item(
                thread_id=active.thread_id,
                run_id=active.run_id,
                kind="reasoning",
                status="streaming",
                payload={"text": initial},
            )
            active.part_items[event.index] = (item, initial)
            self._bus.publish(
                ItemCreatedEvent,
                data=ItemResponse.from_record(item),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            return

        if isinstance(part, (ToolCallPart, BuiltinToolCallPart)):
            args_str = part.args if isinstance(part.args, str) else json.dumps(part.args or {})
            item = self._store.append_item(
                thread_id=active.thread_id,
                run_id=active.run_id,
                kind="tool_call",
                status="streaming",
                payload={
                    "tool_call_id": part.tool_call_id,
                    "tool_name": part.tool_name,
                    "args": _parse_tool_args(part.args),
                    "args_raw": args_str,
                    "output_stream": "",
                    "result": None,
                    "is_error": False,
                },
            )
            active.part_items[event.index] = (item, args_str)
            active.tool_items[part.tool_call_id] = item
            self._bus.publish(
                ItemCreatedEvent,
                data=ItemResponse.from_record(item),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )

    def _handle_part_delta(self, active: _ActiveRun, event: PartDeltaEvent) -> None:
        entry = active.part_items.get(event.index)
        if entry is None:
            return
        item, buf = entry
        delta = event.delta

        if isinstance(delta, TextPartDelta) and delta.content_delta:
            buf += delta.content_delta
            active.part_items[event.index] = (item, buf)
            self._bus.publish(
                ItemDeltaEvent,
                data=ItemDeltaData(item_id=item.id, channel="text", delta=delta.content_delta),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            return

        if isinstance(delta, ThinkingPartDelta) and delta.content_delta:
            buf += delta.content_delta
            active.part_items[event.index] = (item, buf)
            self._bus.publish(
                ItemDeltaEvent,
                data=ItemDeltaData(item_id=item.id, channel="reasoning", delta=delta.content_delta),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            return

        if isinstance(delta, ToolCallPartDelta) and delta.args_delta:
            chunk = (
                delta.args_delta
                if isinstance(delta.args_delta, str)
                else json.dumps(delta.args_delta)
            )
            buf += chunk
            active.part_items[event.index] = (item, buf)
            self._bus.publish(
                ItemDeltaEvent,
                data=ItemDeltaData(item_id=item.id, channel="tool_input", delta=chunk),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )

    def _handle_part_end(self, active: _ActiveRun, event: PartEndEvent) -> None:
        entry = active.part_items.pop(event.index, None)
        if entry is None:
            return
        item, buf = entry
        part = event.part

        if isinstance(part, TextPart):
            final_text = part.content if part.content is not None else buf
            updated = self._store.update_item(item.id, status="completed", payload={"text": final_text})
            self._bus.publish(
                ItemCompletedEvent,
                data=ItemResponse.from_record(updated),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            return

        if isinstance(part, ThinkingPart):
            final_text = part.content if part.content is not None else buf
            updated = self._store.update_item(item.id, status="completed", payload={"text": final_text})
            self._bus.publish(
                ItemCompletedEvent,
                data=ItemResponse.from_record(updated),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            return

        if isinstance(part, (ToolCallPart, BuiltinToolCallPart)):
            # Tool call stays streaming until tool result arrives; persist parsed args
            payload = {
                **item.payload,
                "tool_name": part.tool_name,
                "args": _parse_tool_args(part.args),
                "args_raw": part.args if isinstance(part.args, str) else json.dumps(part.args or {}),
            }
            updated = self._store.update_item(item.id, status="streaming", payload=payload)
            active.tool_items[part.tool_call_id] = updated

    def _handle_tool_call_ready(self, active: _ActiveRun, part: ToolCallPart | BuiltinToolCallPart) -> None:
        item = active.tool_items.get(part.tool_call_id)
        parsed_args = _parse_tool_args(part.args)
        args_raw = part.args if isinstance(part.args, str) else json.dumps(part.args or {})
        if item is None:
            item = self._store.append_item(
                thread_id=active.thread_id,
                run_id=active.run_id,
                kind="tool_call",
                status="streaming",
                payload={
                    "tool_call_id": part.tool_call_id,
                    "tool_name": part.tool_name,
                    "args": parsed_args,
                    "args_raw": args_raw,
                    "output_stream": "",
                    "result": None,
                    "is_error": False,
                },
            )
            active.tool_items[part.tool_call_id] = item
            self._bus.publish(
                ItemCreatedEvent,
                data=ItemResponse.from_record(item),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
        else:
            payload = {
                **item.payload,
                "tool_name": part.tool_name,
                "args": parsed_args,
                "args_raw": args_raw,
            }
            updated = self._store.update_item(item.id, status="streaming", payload=payload)
            active.tool_items[part.tool_call_id] = updated

    def _handle_tool_result(self, active: _ActiveRun, result_part: Any) -> None:
        tool_call_id = getattr(result_part, "tool_call_id", None)
        if not tool_call_id:
            return
        part_kind = getattr(result_part, "part_kind", "")
        is_error = part_kind == "retry-prompt"
        serialized = _serialize_tool_result(getattr(result_part, "content", None))
        if isinstance(serialized, dict) and serialized.get("exit_code") not in (None, 0):
            is_error = True
        if isinstance(serialized, dict) and serialized.get("timed_out"):
            is_error = True

        item = active.tool_items.get(tool_call_id)
        if item is None:
            item = self._store.append_item(
                thread_id=active.thread_id,
                run_id=active.run_id,
                kind="tool_call",
                status="error" if is_error else "completed",
                payload={
                    "tool_call_id": tool_call_id,
                    "tool_name": getattr(result_part, "tool_name", None) or "tool",
                    "args": {},
                    "args_raw": "",
                    "output_stream": active.tool_buffers.get(tool_call_id, ""),
                    "result": serialized,
                    "is_error": is_error,
                },
            )
            active.tool_items[tool_call_id] = item
            self._bus.publish(
                ItemCreatedEvent,
                data=ItemResponse.from_record(item),
                workspace_id=active.workspace_id,
                thread_id=active.thread_id,
                run_id=active.run_id,
            )
            return

        payload = {
            **item.payload,
            "output_stream": active.tool_buffers.get(tool_call_id, item.payload.get("output_stream", "")),
            "result": serialized,
            "is_error": is_error,
        }
        updated = self._store.update_item(
            item.id,
            status="error" if is_error else "completed",
            payload=payload,
        )
        active.tool_items[tool_call_id] = updated
        self._bus.publish(
            ItemCompletedEvent,
            data=ItemResponse.from_record(updated),
            workspace_id=active.workspace_id,
            thread_id=active.thread_id,
            run_id=active.run_id,
        )

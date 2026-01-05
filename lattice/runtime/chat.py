from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelMessage
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import RequestData

from lattice.agents.plugin import AgentRunContext, AgentPlugin
from lattice.domain.agents import select_agent_for_thread
from lattice.domain.messages import merge_messages
from lattice.domain.model_selection import select_session_model
from lattice.domain.threads import load_thread_messages
from lattice.runtime.context import AppContext
from lattice.settings.storage import load_or_create_session_id

logger = logging.getLogger(__name__)


class ChatRequestError(ValueError):
    """Validation or parsing errors for UI chat requests."""


@dataclass(frozen=True)
class ChatRequest:
    session_id: str
    thread_id: str
    run_input: RequestData


@dataclass(frozen=True)
class ChatRun:
    request: ChatRequest
    agent_id: str
    plugin: AgentPlugin
    model_name: str
    adapter: VercelAIAdapter
    message_history: list[ModelMessage]
    run_ctx: AgentRunContext


def parse_run_input(body: bytes) -> RequestData:
    try:
        return VercelAIAdapter.build_run_input(body)
    except Exception as exc:
        raise ChatRequestError(f"Invalid run input: {exc}") from exc


def resolve_chat_request(ctx: AppContext, run_input: RequestData) -> ChatRequest:
    default_session_id = load_or_create_session_id(ctx.config.session_id_path)
    session_id = resolve_session_id_from_request(run_input, default_session_id=default_session_id)
    thread_id = resolve_thread_id_from_request(run_input)
    if not thread_id:
        raise ChatRequestError("Missing thread id.")
    return ChatRequest(session_id=session_id, thread_id=thread_id, run_input=run_input)


def prepare_chat_run(
    ctx: AppContext,
    run_input: RequestData,
    *,
    accept: str | None = None,
) -> ChatRun:
    request = resolve_chat_request(ctx, run_input)
    selection = select_agent_for_thread(
        ctx.store,
        ctx.registry,
        session_id=request.session_id,
        thread_id=request.thread_id,
    )
    plugin = selection.plugin
    model_selection = select_session_model(ctx.store, session_id=request.session_id, plugin=plugin)
    model_name = model_selection.model
    agent = plugin.create_agent(model_name)

    adapter = VercelAIAdapter(agent=agent, run_input=run_input, accept=accept)
    message_history = _load_message_history(ctx, request, run_input)
    _log_message_history(request, selection.agent_id, run_input, message_history)

    run_ctx = AgentRunContext(
        session_id=request.session_id,
        thread_id=request.thread_id,
        model=model_name,
        workspace=ctx.workspace,
        project_root=ctx.project_root,
        run_input=run_input,
    )

    return ChatRun(
        request=request,
        agent_id=selection.agent_id,
        plugin=plugin,
        model_name=model_name,
        adapter=adapter,
        message_history=message_history,
        run_ctx=run_ctx,
    )


def create_chat_stream(
    ctx: AppContext,
    run_input: RequestData,
    *,
    accept: str | None = None,
) -> tuple[VercelAIAdapter, Any]:
    run = prepare_chat_run(ctx, run_input, accept=accept)
    deps = run.plugin.create_deps(run.run_ctx) if run.plugin.create_deps else None
    on_complete = _build_on_complete(
        ctx=ctx,
        request=run.request,
        plugin=run.plugin,
        run_ctx=run.run_ctx,
        adapter=run.adapter,
        message_history=run.message_history,
    )
    stream = run.adapter.run_stream(
        deps=deps,
        message_history=run.message_history,
        on_complete=on_complete,
    )
    return run.adapter, stream


def _resolve_extra_string(run_input: RequestData, *keys: str) -> str | None:
    for key in keys:
        value = getattr(run_input, key, None)
        if isinstance(value, str) and value:
            return value
    return None


def resolve_session_id_from_request(run_input: RequestData, *, default_session_id: str) -> str:
    session_id = _resolve_extra_string(run_input, "session_id", "sessionId")
    return session_id or default_session_id


def resolve_thread_id_from_request(run_input: RequestData) -> str | None:
    return _resolve_extra_string(run_input, "thread_id", "threadId")


def incoming_has_history(run_input: RequestData) -> bool:
    roles = {msg.role for msg in run_input.messages}
    return bool(roles.intersection({"assistant", "system"}))


def select_message_history(run_input: RequestData, stored_messages: Iterable[ModelMessage]) -> list[ModelMessage]:
    if incoming_has_history(run_input):
        return []
    return list(stored_messages)


def _load_message_history(
    ctx: AppContext,
    request: ChatRequest,
    run_input: RequestData,
) -> list[ModelMessage]:
    messages = load_thread_messages(
        ctx.store,
        session_id=request.session_id,
        thread_id=request.thread_id,
    )
    return select_message_history(run_input, messages)


def _log_message_history(
    request: ChatRequest,
    agent_id: str,
    run_input: RequestData,
    message_history: list[ModelMessage],
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    incoming_roles = [msg.role for msg in run_input.messages]
    history_roles = [getattr(msg, "role", None) for msg in message_history]
    logger.debug(
        "ui_chat session=%s thread=%s agent=%s incoming=%s history=%s",
        request.session_id,
        request.thread_id,
        agent_id,
        incoming_roles,
        history_roles,
    )


def _build_on_complete(
    *,
    ctx: AppContext,
    request: ChatRequest,
    plugin: AgentPlugin,
    run_ctx: AgentRunContext,
    adapter: VercelAIAdapter,
    message_history: list[ModelMessage],
):
    def on_complete(result) -> None:
        incoming_messages = adapter.messages
        merged = merge_messages(message_history, incoming_messages, result.new_messages())
        ctx.store.save_thread(request.session_id, request.thread_id, messages=merged)
        if plugin.on_complete:
            plugin.on_complete(run_ctx, result)

    return on_complete

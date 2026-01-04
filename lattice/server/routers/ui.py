from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic_ai.exceptions import UserError
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.request_types import RequestData

from lattice.agents.plugin import AgentRunContext
from lattice.config import load_or_create_session_id
from lattice.core.messages import merge_messages
from lattice.server.context import AppContext
from lattice.server.deps import get_ctx
from lattice.server.services.agents import select_agent_for_thread
from lattice.server.services.models import select_session_model
from lattice.server.services.sessions import (
    resolve_session_id_from_request,
    resolve_thread_id_from_request,
    select_message_history,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ui/chat")
async def ui_chat(request: Request, ctx: AppContext = Depends(get_ctx)):
    run_input = await _read_run_input(request)
    session_id, thread_id = _resolve_session_and_thread(ctx, run_input)

    agent_selection = select_agent_for_thread(ctx, session_id=session_id, thread_id=thread_id)
    plugin = agent_selection.plugin
    model_selection = select_session_model(ctx, session_id=session_id, plugin=plugin)
    model_name = model_selection.model
    agent = _create_agent(plugin, model_name)

    adapter = VercelAIAdapter(agent=agent, run_input=run_input, accept=request.headers.get("accept"))
    message_history = _load_message_history(ctx, session_id, thread_id, run_input)
    _log_message_history(session_id, thread_id, agent_selection.agent_id, run_input, message_history)

    run_ctx = AgentRunContext(
        session_id=session_id,
        thread_id=thread_id,
        model=model_name,
        workspace=ctx.workspace,
        project_root=ctx.project_root,
        run_input=run_input,
    )
    deps = plugin.create_deps(run_ctx) if plugin.create_deps else None
    on_complete = _build_on_complete(
        ctx=ctx,
        session_id=session_id,
        thread_id=thread_id,
        plugin=plugin,
        run_ctx=run_ctx,
        adapter=adapter,
        message_history=message_history,
    )

    stream = adapter.run_stream(deps=deps, message_history=message_history, on_complete=on_complete)
    return adapter.streaming_response(stream)


async def _read_run_input(request: Request) -> RequestData:
    body = await request.body()
    return VercelAIAdapter.build_run_input(body)


def _resolve_session_and_thread(ctx: AppContext, run_input: RequestData) -> tuple[str, str]:
    default_session_id = load_or_create_session_id(ctx.config.session_id_path)
    session_id = resolve_session_id_from_request(run_input, default_session_id=default_session_id)
    thread_id = resolve_thread_id_from_request(run_input)
    if not thread_id:
        raise HTTPException(status_code=400, detail="Missing thread id.")
    return session_id, thread_id


def _create_agent(plugin, model_name: str):
    try:
        return plugin.create_agent(model_name)
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _load_message_history(
    ctx: AppContext,
    session_id: str,
    thread_id: str,
    run_input: RequestData,
):
    thread_state = ctx.store.load_thread(session_id, thread_id, workspace=ctx.workspace)
    return select_message_history(run_input, thread_state.messages)


def _log_message_history(
    session_id: str,
    thread_id: str,
    agent_id: str,
    run_input: RequestData,
    message_history,
) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    incoming_roles = [msg.role for msg in run_input.messages]
    history_roles = [getattr(msg, "role", None) for msg in message_history]
    logger.debug(
        "ui_chat session=%s thread=%s agent=%s incoming=%s history=%s",
        session_id,
        thread_id,
        agent_id,
        incoming_roles,
        history_roles,
    )


def _build_on_complete(
    *,
    ctx: AppContext,
    session_id: str,
    thread_id: str,
    plugin,
    run_ctx: AgentRunContext,
    adapter: VercelAIAdapter,
    message_history,
):
    def on_complete(result) -> None:
        incoming_messages = adapter.messages
        merged = merge_messages(message_history, incoming_messages, result.new_messages())
        ctx.store.save_thread(session_id, thread_id, workspace=ctx.workspace, messages=merged)
        if plugin.on_complete:
            plugin.on_complete(run_ctx, result)

    return on_complete

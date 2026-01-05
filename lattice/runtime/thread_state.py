from __future__ import annotations

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from lattice.runtime.context import AppContext
from lattice.domain.agents import select_agent_for_thread, set_thread_agent
from lattice.domain.model_selection import (
    build_model_list,
    select_session_model,
    set_session_model,
)
from lattice.domain.threads import load_thread_messages, require_thread
from lattice.protocol.schemas import (
    ModelListResponse,
    SessionModelResponse,
    ThreadAgentResponse,
    ThreadStateResponse,
    ThreadStateUpdateRequest,
)


def build_thread_state(
    ctx: AppContext,
    *,
    session_id: str,
    thread_id: str,
) -> ThreadStateResponse:
    selection = select_agent_for_thread(ctx.store, ctx.registry, session_id=session_id, thread_id=thread_id)
    model_selection = select_session_model(ctx.store, session_id=session_id, plugin=selection.plugin)
    messages = load_thread_messages(ctx.store, session_id=session_id, thread_id=thread_id)
    ui_messages = VercelAIAdapter.dump_messages(messages)
    return ThreadStateResponse(
        thread_id=thread_id,
        agent=ThreadAgentResponse(
            agent=selection.agent_id,
            default_agent=selection.default_agent_id,
            is_default=selection.is_default,
            agent_name=selection.agent_name,
        ),
        model=SessionModelResponse(
            model=model_selection.model,
            default_model=model_selection.default_model,
            is_default=model_selection.is_default,
        ),
        messages=ui_messages,
    )


def update_thread_state(
    ctx: AppContext,
    *,
    session_id: str,
    thread_id: str,
    payload: ThreadStateUpdateRequest,
) -> ThreadStateResponse:
    require_thread(ctx.store, session_id=session_id, thread_id=thread_id)
    selection = select_agent_for_thread(ctx.store, ctx.registry, session_id=session_id, thread_id=thread_id)

    if "agent" in payload.model_fields_set:
        selection = set_thread_agent(
            ctx.store,
            ctx.registry,
            session_id=session_id,
            thread_id=thread_id,
            requested=payload.agent,
        )

    if "model" in payload.model_fields_set:
        set_session_model(
            ctx.store,
            session_id=session_id,
            plugin=selection.plugin,
            requested=payload.model,
        )

    return build_thread_state(ctx, session_id=session_id, thread_id=thread_id)


def list_thread_models(
    ctx: AppContext,
    *,
    session_id: str,
    thread_id: str,
) -> ModelListResponse:
    require_thread(ctx.store, session_id=session_id, thread_id=thread_id)
    selection = select_agent_for_thread(ctx.store, ctx.registry, session_id=session_id, thread_id=thread_id)
    default_model, models = build_model_list(selection.plugin)
    return ModelListResponse(default_model=default_model, models=models)

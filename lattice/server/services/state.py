from __future__ import annotations

from pydantic_ai.ui.vercel_ai import VercelAIAdapter

from lattice.core.threads import load_thread_messages
from lattice.protocol.models import SessionModelResponse, ThreadAgentResponse, ThreadStateResponse
from lattice.server.context import AppContext
from lattice.server.services.agents import select_agent_for_thread
from lattice.server.services.models import select_session_model


def build_thread_state(
    ctx: AppContext,
    *,
    session_id: str,
    thread_id: str,
) -> ThreadStateResponse:
    selection = select_agent_for_thread(ctx, session_id=session_id, thread_id=thread_id)
    model_selection = select_session_model(ctx, session_id=session_id, plugin=selection.plugin)
    messages = load_thread_messages(ctx.store, session_id=session_id, thread_id=thread_id, workspace=ctx.workspace)
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

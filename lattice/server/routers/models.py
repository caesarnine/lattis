from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from lattice.core.threads import list_threads
from lattice.protocol.models import ModelListResponse
from lattice.server.context import AppContext
from lattice.server.deps import get_ctx
from lattice.server.services.agents import select_agent_for_thread
from lattice.server.services.models import list_models, resolve_default_model

router = APIRouter()


@router.get(
    "/sessions/{session_id}/threads/{thread_id}/models",
    response_model=ModelListResponse,
)
async def api_list_thread_models(
    session_id: str,
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ModelListResponse:
    if thread_id not in list_threads(ctx.store, session_id):
        raise HTTPException(status_code=404, detail="Thread not found.")
    selection = select_agent_for_thread(ctx, session_id=session_id, thread_id=thread_id)
    default_model = resolve_default_model(selection.plugin)
    return ModelListResponse(default_model=default_model, models=list_models(selection.plugin))

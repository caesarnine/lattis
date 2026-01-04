from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic_ai.exceptions import UserError

from lattice.protocol.models import (
    ModelListResponse,
    SessionModelRequest,
    SessionModelResponse,
)
from lattice.server.context import AppContext
from lattice.server.deps import get_ctx
from lattice.server.services.agents import get_default_plugin
from lattice.server.services.models import (
    list_models,
    resolve_default_model,
    select_session_model,
    set_session_model,
)

router = APIRouter()


@router.get("/models", response_model=ModelListResponse)
async def api_list_models(ctx: AppContext = Depends(get_ctx)) -> ModelListResponse:
    plugin = get_default_plugin(ctx)
    default_model = resolve_default_model(plugin)
    return ModelListResponse(default_model=default_model, models=list_models(plugin))


@router.get("/sessions/{session_id}/model", response_model=SessionModelResponse)
async def api_get_session_model(session_id: str, ctx: AppContext = Depends(get_ctx)) -> SessionModelResponse:
    plugin = get_default_plugin(ctx)
    selection = select_session_model(ctx, session_id=session_id, plugin=plugin)
    return SessionModelResponse(
        model=selection.model,
        default_model=selection.default_model,
        is_default=selection.is_default,
    )


@router.put("/sessions/{session_id}/model", response_model=SessionModelResponse)
async def api_set_session_model(
    session_id: str,
    payload: SessionModelRequest,
    ctx: AppContext = Depends(get_ctx),
) -> SessionModelResponse:
    plugin = get_default_plugin(ctx)
    try:
        selection = set_session_model(
            ctx,
            session_id=session_id,
            plugin=plugin,
            requested=payload.model,
        )
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SessionModelResponse(
        model=selection.model,
        default_model=selection.default_model,
        is_default=selection.is_default,
    )

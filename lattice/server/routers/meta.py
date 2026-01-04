from __future__ import annotations

import importlib.metadata
import os

from fastapi import APIRouter, Depends

from lattice.config import load_or_create_session_id
from lattice.protocol.models import ServerInfoResponse
from lattice.server.context import AppContext
from lattice.server.deps import get_ctx
from lattice.server.services.agents import get_default_plugin

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/info", response_model=ServerInfoResponse)
async def info(ctx: AppContext = Depends(get_ctx)) -> ServerInfoResponse:
    default_plugin = get_default_plugin(ctx)
    try:
        version = importlib.metadata.version("lattice")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        version = "unknown"
    return ServerInfoResponse(
        version=version,
        pid=os.getpid(),
        project_root=str(ctx.project_root),
        data_dir=str(ctx.config.data_dir),
        workspace_dir=str(ctx.workspace),
        workspace_mode=ctx.config.workspace_mode,
        agent_name=default_plugin.name,
    )


@router.get("/session")
async def api_session(ctx: AppContext = Depends(get_ctx)) -> dict[str, str]:
    session_id = load_or_create_session_id(ctx.config.session_id_path)
    return {"session_id": session_id}

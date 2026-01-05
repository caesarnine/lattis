from __future__ import annotations

import importlib.metadata
import os

from fastapi import APIRouter, Depends

from lattice.app.bootstrap import bootstrap_session
from lattice.protocol.schemas import ServerInfoResponse, SessionBootstrapResponse
from lattice.app.context import AppContext
from lattice.server.deps import get_ctx
from lattice.domain.agents import get_default_plugin

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/info", response_model=ServerInfoResponse)
async def info(ctx: AppContext = Depends(get_ctx)) -> ServerInfoResponse:
    default_plugin = get_default_plugin(ctx.registry)
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


@router.get("/session/bootstrap", response_model=SessionBootstrapResponse)
async def api_session_bootstrap(
    thread_id: str | None = None,
    ctx: AppContext = Depends(get_ctx),
) -> SessionBootstrapResponse:
    return bootstrap_session(ctx, thread_id=thread_id)

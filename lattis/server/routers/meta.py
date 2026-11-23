from __future__ import annotations

import importlib.metadata
import os

from fastapi import APIRouter, Depends

from lattis.protocol.schemas import HealthResponse, ServerInfoResponse
from lattis.runtime.context import AppContext
from lattis.server.deps import get_ctx, require_auth

router = APIRouter()


def get_lattis_version() -> str:
    try:
        return importlib.metadata.version("lattis")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover
        return "unknown"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/info", response_model=ServerInfoResponse, dependencies=[Depends(require_auth)])
async def info(ctx: AppContext = Depends(get_ctx)) -> ServerInfoResponse:
    return ServerInfoResponse(
        version=get_lattis_version(),
        pid=os.getpid(),
        lattis_home=str(ctx.config.home_dir),
        default_agent=ctx.registry.default_agent,
        active_runs=ctx.run_manager.active_run_count,
        auth_enabled=ctx.auth_token is not None,
    )

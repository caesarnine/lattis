from __future__ import annotations

import importlib.metadata
import os

from fastapi import APIRouter, Depends

from lattice.config import load_or_create_session_id
from lattice.core.threads import create_thread, list_threads
from lattice.protocol.models import ServerInfoResponse, SessionBootstrapResponse
from lattice.server.context import AppContext
from lattice.server.deps import get_ctx
from lattice.server.services.agents import get_default_plugin
from lattice.server.services.state import build_thread_state

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


@router.get("/session/bootstrap", response_model=SessionBootstrapResponse)
async def api_session_bootstrap(
    thread_id: str | None = None,
    ctx: AppContext = Depends(get_ctx),
) -> SessionBootstrapResponse:
    session_id = load_or_create_session_id(ctx.config.session_id_path)
    threads = list_threads(ctx.store, session_id)

    requested = (thread_id or "").strip()
    if requested:
        selected_thread = requested
    elif threads:
        selected_thread = threads[0]
    else:
        selected_thread = "default"

    if selected_thread not in threads:
        try:
            create_thread(ctx.store, session_id=session_id, thread_id=selected_thread, workspace=ctx.workspace)
        except ValueError:
            pass
        threads = list_threads(ctx.store, session_id)

    state = build_thread_state(ctx, session_id=session_id, thread_id=selected_thread)
    return SessionBootstrapResponse(
        session_id=session_id,
        thread_id=selected_thread,
        threads=threads,
        agent=state.agent,
        model=state.model,
        messages=state.messages,
    )

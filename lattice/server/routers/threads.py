from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic_ai.exceptions import UserError
from lattice.core.session import generate_thread_id
from lattice.core.threads import create_thread, delete_thread, list_threads
from lattice.protocol.models import (
    ThreadClearResponse,
    ThreadCreateRequest,
    ThreadCreateResponse,
    ThreadDeleteResponse,
    ThreadListResponse,
    ThreadStateResponse,
    ThreadStateUpdateRequest,
)
from lattice.server.context import AppContext
from lattice.server.deps import get_ctx
from lattice.server.services.agents import select_agent_for_thread, set_thread_agent
from lattice.server.services.models import set_session_model
from lattice.server.services.state import build_thread_state

router = APIRouter()


@router.get("/sessions/{session_id}/threads", response_model=ThreadListResponse)
async def api_list_threads(session_id: str, ctx: AppContext = Depends(get_ctx)) -> ThreadListResponse:
    return ThreadListResponse(threads=list_threads(ctx.store, session_id))


@router.post("/sessions/{session_id}/threads", response_model=ThreadCreateResponse)
async def api_create_thread(
    session_id: str,
    payload: ThreadCreateRequest,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadCreateResponse:
    thread_id = payload.thread_id or ""
    if not thread_id:
        thread_id = generate_thread_id()
    try:
        create_thread(ctx.store, session_id=session_id, thread_id=thread_id, workspace=ctx.workspace)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ThreadCreateResponse(thread_id=thread_id)


@router.delete("/sessions/{session_id}/threads/{thread_id}", response_model=ThreadDeleteResponse)
async def api_delete_thread(
    session_id: str,
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadDeleteResponse:
    if thread_id not in list_threads(ctx.store, session_id):
        raise HTTPException(status_code=404, detail="Thread not found.")
    delete_thread(ctx.store, session_id=session_id, thread_id=thread_id)
    return ThreadDeleteResponse(deleted=thread_id)


@router.post(
    "/sessions/{session_id}/threads/{thread_id}/clear",
    response_model=ThreadClearResponse,
)
async def api_clear_thread(
    session_id: str,
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadClearResponse:
    if thread_id not in list_threads(ctx.store, session_id):
        raise HTTPException(status_code=404, detail="Thread not found.")
    ctx.store.save_thread(session_id, thread_id, workspace=ctx.workspace, messages=[])
    return ThreadClearResponse(cleared=thread_id)


@router.get(
    "/sessions/{session_id}/threads/{thread_id}/state",
    response_model=ThreadStateResponse,
)
async def api_thread_state(
    session_id: str,
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadStateResponse:
    if thread_id not in list_threads(ctx.store, session_id):
        raise HTTPException(status_code=404, detail="Thread not found.")
    return build_thread_state(ctx, session_id=session_id, thread_id=thread_id)


@router.patch(
    "/sessions/{session_id}/threads/{thread_id}/state",
    response_model=ThreadStateResponse,
)
async def api_update_thread_state(
    session_id: str,
    thread_id: str,
    payload: ThreadStateUpdateRequest,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadStateResponse:
    if thread_id not in list_threads(ctx.store, session_id):
        raise HTTPException(status_code=404, detail="Thread not found.")

    selection = select_agent_for_thread(ctx, session_id=session_id, thread_id=thread_id)

    if "agent" in payload.model_fields_set:
        try:
            selection = set_thread_agent(
                ctx,
                session_id=session_id,
                thread_id=thread_id,
                requested=payload.agent,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if "model" in payload.model_fields_set:
        try:
            set_session_model(
                ctx,
                session_id=session_id,
                plugin=selection.plugin,
                requested=payload.model,
            )
        except UserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return build_thread_state(ctx, session_id=session_id, thread_id=thread_id)

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic_ai.exceptions import UserError
from lattice.domain.sessions import generate_thread_id
from lattice.domain.threads import (
    ThreadAlreadyExistsError,
    ThreadNotFoundError,
    clear_thread,
    create_thread,
    delete_thread,
    list_threads,
)
from lattice.protocol.schemas import (
    ThreadClearResponse,
    ThreadCreateRequest,
    ThreadCreateResponse,
    ThreadDeleteResponse,
    ThreadListResponse,
    ThreadStateResponse,
    ThreadStateUpdateRequest,
)
from lattice.app.context import AppContext
from lattice.app.thread_state import build_thread_state, update_thread_state
from lattice.server.deps import get_ctx

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
        create_thread(ctx.store, session_id=session_id, thread_id=thread_id)
    except ThreadAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ThreadCreateResponse(thread_id=thread_id)


@router.delete("/sessions/{session_id}/threads/{thread_id}", response_model=ThreadDeleteResponse)
async def api_delete_thread(
    session_id: str,
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadDeleteResponse:
    try:
        delete_thread(ctx.store, session_id=session_id, thread_id=thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        clear_thread(ctx.store, session_id=session_id, thread_id=thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
    try:
        return build_thread_state(ctx, session_id=session_id, thread_id=thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    try:
        return update_thread_state(ctx, session_id=session_id, thread_id=thread_id, payload=payload)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

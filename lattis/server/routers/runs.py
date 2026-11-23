from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from lattis.domain.errors import (
    ApprovalNotFoundError,
    RunNotFoundError,
    ThreadBusyError,
    ThreadNotFoundError,
    WorkspaceNotFoundError,
)
from lattis.protocol.schemas import (
    ApprovalResolveRequest,
    ApprovalResolveResponse,
    ItemResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunListResponse,
    RunResponse,
)
from lattis.runtime.context import AppContext
from lattis.server.deps import get_ctx, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.post("/threads/{thread_id}/runs", response_model=RunCreateResponse, status_code=202)
async def api_start_run(
    thread_id: str,
    payload: RunCreateRequest,
    ctx: AppContext = Depends(get_ctx),
) -> RunCreateResponse:
    try:
        run, user_item = await ctx.run_manager.start_run(
            thread_id=thread_id,
            user_input=payload.input,
        )
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ThreadBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return RunCreateResponse(
        run=RunResponse.from_record(run),
        user_item=ItemResponse.from_record(user_item),
    )


@router.get("/threads/{thread_id}/runs", response_model=RunListResponse)
async def api_list_runs(
    thread_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
) -> RunListResponse:
    try:
        runs = ctx.store.list_runs(thread_id, limit=limit)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunListResponse(runs=[RunResponse.from_record(r) for r in runs])


@router.get("/runs/{run_id}", response_model=RunResponse)
async def api_get_run(
    run_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> RunResponse:
    run = ctx.store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found.")
    return RunResponse.from_record(run)


@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def api_cancel_run(
    run_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> RunResponse:
    try:
        run = await ctx.run_manager.cancel_run(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunResponse.from_record(run)


@router.post("/runs/{run_id}/approvals/{approval_id}", response_model=ApprovalResolveResponse)
async def api_resolve_approval(
    run_id: str,
    approval_id: str,
    payload: ApprovalResolveRequest,
    ctx: AppContext = Depends(get_ctx),
) -> ApprovalResolveResponse:
    try:
        run, item = await ctx.run_manager.resolve_approval(
            run_id=run_id,
            approval_id=approval_id,
            approved=payload.approved,
            reason=payload.reason,
        )
    except ApprovalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ApprovalResolveResponse(
        run=RunResponse.from_record(run),
        approval_item=ItemResponse.from_record(item),
    )

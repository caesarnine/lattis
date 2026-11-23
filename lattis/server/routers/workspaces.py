from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from lattis.domain.errors import WorkspaceNotFoundError, WorkspaceProtectedError
from lattis.protocol.schemas import (
    WorkspaceCreatedEvent,
    WorkspaceCreateRequest,
    WorkspaceDeletedData,
    WorkspaceDeletedEvent,
    WorkspaceDeleteResponse,
    WorkspaceListResponse,
    WorkspaceResponse,
    WorkspaceUpdatedEvent,
    WorkspaceUpdateRequest,
)
from lattis.runtime.context import AppContext
from lattis.server.deps import get_ctx, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/workspaces", response_model=WorkspaceListResponse)
async def api_list_workspaces(ctx: AppContext = Depends(get_ctx)) -> WorkspaceListResponse:
    records = ctx.store.list_workspaces()
    return WorkspaceListResponse(
        workspaces=[
            WorkspaceResponse.from_record(
                rec,
                thread_count=ctx.store.count_workspace_threads(rec.id),
            )
            for rec in records
        ]
    )


@router.post("/workspaces", response_model=WorkspaceResponse)
async def api_register_workspace(
    payload: WorkspaceCreateRequest,
    ctx: AppContext = Depends(get_ctx),
) -> WorkspaceResponse:
    raw_path = payload.root_path.strip()
    if not raw_path:
        raise HTTPException(status_code=400, detail="Workspace root_path cannot be empty.")
    resolved_name = (payload.name or "").strip() or Path(raw_path).expanduser().name or raw_path
    record, created = ctx.store.upsert_workspace(root_path=raw_path, name=resolved_name, kind="project")
    response = WorkspaceResponse.from_record(
        record,
        thread_count=ctx.store.count_workspace_threads(record.id),
    )
    if created:
        ctx.bus.publish(WorkspaceCreatedEvent, data=response, workspace_id=record.id)
    return response


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def api_get_workspace(
    workspace_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> WorkspaceResponse:
    record = ctx.store.get_workspace(workspace_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return WorkspaceResponse.from_record(
        record,
        thread_count=ctx.store.count_workspace_threads(record.id),
    )


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceResponse)
async def api_update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdateRequest,
    ctx: AppContext = Depends(get_ctx),
) -> WorkspaceResponse:
    try:
        record = ctx.store.update_workspace(
            workspace_id,
            name=payload.name if "name" in payload.model_fields_set else None,
            settings=payload.settings if "settings" in payload.model_fields_set else None,
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    response = WorkspaceResponse.from_record(
        record,
        thread_count=ctx.store.count_workspace_threads(record.id),
    )
    ctx.bus.publish(WorkspaceUpdatedEvent, data=response, workspace_id=record.id)
    return response


@router.delete("/workspaces/{workspace_id}", response_model=WorkspaceDeleteResponse)
async def api_delete_workspace(
    workspace_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> WorkspaceDeleteResponse:
    # Cancel any active runs on threads in this workspace before deleting
    try:
        threads = ctx.store.list_threads(workspace_id)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    for thread in threads:
        await ctx.run_manager.cancel_thread_run(thread.id)

    try:
        ctx.store.delete_workspace(workspace_id)
    except WorkspaceProtectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ctx.bus.publish(
        WorkspaceDeletedEvent,
        data=WorkspaceDeletedData(workspace_id=workspace_id),
        workspace_id=workspace_id,
    )
    return WorkspaceDeleteResponse(deleted=workspace_id)

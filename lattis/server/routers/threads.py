from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic_ai.exceptions import UserError

from lattis.domain.agents import resolve_requested_agent, select_agent_for_thread
from lattis.domain.errors import (
    ThreadAlreadyExistsError,
    ThreadNotFoundError,
    WorkspaceNotFoundError,
)
from lattis.domain.model_selection import build_model_list, validate_requested_model
from lattis.protocol.schemas import (
    ItemListResponse,
    ItemResponse,
    ModelListResponse,
    ThreadClearedEvent,
    ThreadClearResponse,
    ThreadCreatedEvent,
    ThreadCreateRequest,
    ThreadDeletedEvent,
    ThreadDeleteResponse,
    ThreadIdData,
    ThreadListResponse,
    ThreadResponse,
    ThreadUpdatedEvent,
    ThreadUpdateRequest,
)
from lattis.runtime.context import AppContext
from lattis.server.deps import get_ctx, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/workspaces/{workspace_id}/threads", response_model=ThreadListResponse)
async def api_list_threads(
    workspace_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadListResponse:
    workspace = ctx.store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    threads = ctx.store.list_threads(workspace_id)
    return ThreadListResponse(
        threads=[ctx.run_manager.build_thread_response(t, workspace=workspace) for t in threads]
    )


@router.post("/workspaces/{workspace_id}/threads", response_model=ThreadResponse)
async def api_create_thread(
    workspace_id: str,
    payload: ThreadCreateRequest,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadResponse:
    workspace = ctx.store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")

    resolved_agent_id: str | None = None
    plugin = ctx.registry.agents[ctx.registry.default_agent]
    if payload.agent_id is not None and payload.agent_id.strip():
        try:
            selection = resolve_requested_agent(
                ctx.registry,
                payload.agent_id,
                allow_fuzzy=True,
                workspace=workspace,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        resolved_agent_id = selection.agent_id
        plugin = selection.plugin

    resolved_model: str | None = None
    if payload.model is not None and payload.model.strip():
        try:
            resolved_model = validate_requested_model(plugin, payload.model)
        except (ValueError, UserError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        record = ctx.store.create_thread(
            workspace_id=workspace_id,
            thread_id=payload.thread_id,
            title=payload.title,
            agent_id=resolved_agent_id,
            model=resolved_model,
            settings=payload.settings,
        )
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ThreadAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    response = ctx.run_manager.build_thread_response(record, workspace=workspace)
    ctx.bus.publish(
        ThreadCreatedEvent,
        data=response,
        workspace_id=workspace_id,
        thread_id=record.id,
    )
    return response


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
async def api_get_thread(
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadResponse:
    record = ctx.store.get_thread(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")
    return ctx.run_manager.build_thread_response(record)


@router.patch("/threads/{thread_id}", response_model=ThreadResponse)
async def api_update_thread(
    thread_id: str,
    payload: ThreadUpdateRequest,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadResponse:
    record = ctx.store.get_thread(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")
    workspace = ctx.store.get_workspace(record.workspace_id)

    update_kwargs: dict[str, object] = {}
    if "title" in payload.model_fields_set and payload.title is not None:
        update_kwargs["title"] = payload.title

    selection = select_agent_for_thread(ctx.registry, record, workspace=workspace)
    if "agent_id" in payload.model_fields_set:
        if payload.agent_id is None or not payload.agent_id.strip():
            update_kwargs["agent_id"] = None
            temp = record
            temp.agent_id = None
            selection = select_agent_for_thread(ctx.registry, temp, workspace=workspace)
        else:
            try:
                selection = resolve_requested_agent(
                    ctx.registry,
                    payload.agent_id,
                    allow_fuzzy=True,
                    workspace=workspace,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            update_kwargs["agent_id"] = selection.agent_id

    if "model" in payload.model_fields_set:
        if payload.model is None or not payload.model.strip():
            update_kwargs["model"] = None
        else:
            try:
                validated = validate_requested_model(selection.plugin, payload.model)
            except (ValueError, UserError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            update_kwargs["model"] = validated

    if "settings" in payload.model_fields_set and payload.settings is not None:
        update_kwargs["settings"] = payload.settings

    updated = ctx.store.update_thread(thread_id, **update_kwargs)  # type: ignore[arg-type]
    response = ctx.run_manager.build_thread_response(updated, workspace=workspace)
    ctx.bus.publish(
        ThreadUpdatedEvent,
        data=response,
        workspace_id=updated.workspace_id,
        thread_id=updated.id,
    )
    return response


@router.delete("/threads/{thread_id}", response_model=ThreadDeleteResponse)
async def api_delete_thread(
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadDeleteResponse:
    record = ctx.store.get_thread(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")
    await ctx.run_manager.cancel_thread_run(thread_id)
    try:
        ctx.store.delete_thread(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ctx.bus.publish(
        ThreadDeletedEvent,
        data=ThreadIdData(thread_id=thread_id),
        workspace_id=record.workspace_id,
        thread_id=thread_id,
    )
    return ThreadDeleteResponse(deleted=thread_id)


@router.post("/threads/{thread_id}/clear", response_model=ThreadClearResponse)
async def api_clear_thread(
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadClearResponse:
    record = ctx.store.get_thread(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")
    await ctx.run_manager.cancel_thread_run(thread_id)
    try:
        ctx.store.clear_thread(thread_id)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ctx.bus.publish(
        ThreadClearedEvent,
        data=ThreadIdData(thread_id=thread_id),
        workspace_id=record.workspace_id,
        thread_id=thread_id,
    )
    return ThreadClearResponse(cleared=thread_id)


@router.get("/threads/{thread_id}/models", response_model=ModelListResponse)
async def api_list_thread_models(
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ModelListResponse:
    record = ctx.store.get_thread(thread_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Thread '{thread_id}' not found.")
    workspace = ctx.store.get_workspace(record.workspace_id)
    selection = select_agent_for_thread(ctx.registry, record, workspace=workspace)
    default_model, models = build_model_list(selection.plugin, workspace=workspace)
    return ModelListResponse(default_model=default_model, models=models)


@router.get("/threads/{thread_id}/items", response_model=ItemListResponse)
async def api_list_thread_items(
    thread_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    ctx: AppContext = Depends(get_ctx),
) -> ItemListResponse:
    try:
        items, has_more = ctx.store.list_items(thread_id, after_seq=after_seq, limit=limit)
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ItemListResponse(
        items=[ItemResponse.from_record(item) for item in items],
        has_more=has_more,
    )

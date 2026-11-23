from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from lattis.protocol.schemas import (
    FileEntryResponse,
    GitDiffResponse,
    GitFileStatusResponse,
    GitStatusResponse,
    WorkspaceFileReadResponse,
    WorkspaceFilesResponse,
)
from lattis.runtime.context import AppContext
from lattis.runtime.workspace_fs import (
    DEFAULT_MAX_DIFF_CHARS,
    DEFAULT_MAX_FILE_BYTES,
    WorkspacePathError,
    get_git_diff,
    get_git_status,
    list_workspace_files,
    read_workspace_file,
)
from lattis.server.deps import get_ctx, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


def _require_workspace_root(ctx: AppContext, workspace_id: str) -> Path:
    workspace = ctx.store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")
    return Path(workspace.root_path)


@router.get("/workspaces/{workspace_id}/files", response_model=WorkspaceFilesResponse)
async def api_list_workspace_files(
    workspace_id: str,
    path: str = Query(default=""),
    include_hidden: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=2000),
    ctx: AppContext = Depends(get_ctx),
) -> WorkspaceFilesResponse:
    root = _require_workspace_root(ctx, workspace_id)
    try:
        normalized_path, entries = list_workspace_files(
            root,
            rel_path=path,
            include_hidden=include_hidden,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return WorkspaceFilesResponse(
        workspace_id=workspace_id,
        path=normalized_path,
        entries=[
            FileEntryResponse(
                name=e.name,
                path=e.path,
                kind=e.kind,
                size=e.size,
                mtime=e.mtime,
            )
            for e in entries
        ],
    )


@router.get("/workspaces/{workspace_id}/file", response_model=WorkspaceFileReadResponse)
async def api_read_workspace_file(
    workspace_id: str,
    path: str = Query(..., min_length=1),
    max_bytes: int = Query(default=DEFAULT_MAX_FILE_BYTES, ge=1, le=2_097_152),
    ctx: AppContext = Depends(get_ctx),
) -> WorkspaceFileReadResponse:
    root = _require_workspace_root(ctx, workspace_id)
    try:
        data = read_workspace_file(root, rel_path=path, max_bytes=max_bytes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return WorkspaceFileReadResponse(
        workspace_id=workspace_id,
        path=data.path,
        content=data.content,
        size=data.size,
        is_binary=data.is_binary,
        truncated=data.truncated,
    )


@router.get("/workspaces/{workspace_id}/git/status", response_model=GitStatusResponse)
async def api_workspace_git_status(
    workspace_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> GitStatusResponse:
    root = _require_workspace_root(ctx, workspace_id)
    data = await get_git_status(root)
    return GitStatusResponse(
        workspace_id=workspace_id,
        is_git_repo=data.is_git_repo,
        branch=data.branch,
        ahead=data.ahead,
        behind=data.behind,
        files=[
            GitFileStatusResponse(
                path=f.path,
                index_status=f.index_status,
                worktree_status=f.worktree_status,
                status=f.status,
            )
            for f in data.files
        ],
    )


@router.get("/workspaces/{workspace_id}/git/diff", response_model=GitDiffResponse)
async def api_workspace_git_diff(
    workspace_id: str,
    path: str | None = Query(default=None),
    staged: bool = Query(default=False),
    max_chars: int = Query(default=DEFAULT_MAX_DIFF_CHARS, ge=1024, le=1_000_000),
    ctx: AppContext = Depends(get_ctx),
) -> GitDiffResponse:
    root = _require_workspace_root(ctx, workspace_id)
    try:
        data = await get_git_diff(root, rel_path=path, staged=staged, max_chars=max_chars)
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return GitDiffResponse(
        workspace_id=workspace_id,
        is_git_repo=data.is_git_repo,
        path=data.path,
        staged=data.staged,
        diff=data.diff,
        truncated=data.truncated,
    )

from __future__ import annotations

import inspect
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from lattis.agents.plugin import PluginStateContext
from lattis.protocol.schemas import PluginStateResponse
from lattis.runtime.context import AppContext
from lattis.server.deps import get_ctx, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/workspaces/{workspace_id}/plugins/{agent_id}/state", response_model=PluginStateResponse)
async def api_get_plugin_state(
    workspace_id: str,
    agent_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> PluginStateResponse:
    workspace = ctx.store.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace '{workspace_id}' not found.")

    plugin = ctx.registry.get(agent_id)
    if plugin is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    if plugin.get_state is None:
        return PluginStateResponse(workspace_id=workspace_id, agent_id=agent_id, state=None)

    state_ctx = PluginStateContext(
        workspace_id=workspace.id,
        project_root=Path(workspace.root_path),
        plugin_data_dir=ctx.plugin_data_dir(plugin.id),
        workspace_data_dir=ctx.workspace_data_dir(workspace.id, plugin.id),
    )
    raw = plugin.get_state(state_ctx)
    state = await raw if inspect.isawaitable(raw) else raw
    return PluginStateResponse(workspace_id=workspace_id, agent_id=agent_id, state=state)

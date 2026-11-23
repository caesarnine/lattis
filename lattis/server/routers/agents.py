from __future__ import annotations

from fastapi import APIRouter, Depends

from lattis.domain.model_selection import resolve_default_model
from lattis.protocol.schemas import AgentInfo, AgentListResponse
from lattis.runtime.context import AppContext
from lattis.server.deps import get_ctx, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])


@router.get("/agents", response_model=AgentListResponse)
async def api_list_agents(ctx: AppContext = Depends(get_ctx)) -> AgentListResponse:
    agents: list[AgentInfo] = []
    for spec in ctx.registry.list_specs():
        plugin = ctx.registry.agents[spec.id]
        agents.append(
            AgentInfo(
                id=spec.id,
                name=spec.name,
                default_model=resolve_default_model(plugin) or None,
                has_state=plugin.get_state is not None,
            )
        )
    return AgentListResponse(default_agent=ctx.registry.default_agent, agents=agents)

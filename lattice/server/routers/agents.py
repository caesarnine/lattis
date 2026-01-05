from __future__ import annotations

from fastapi import APIRouter, Depends

from lattice.protocol.schemas import AgentInfo, AgentListResponse
from lattice.app.context import AppContext
from lattice.server.deps import get_ctx

router = APIRouter()


@router.get("/agents", response_model=AgentListResponse)
async def api_list_agents(ctx: AppContext = Depends(get_ctx)) -> AgentListResponse:
    agents = [AgentInfo(id=spec.id, name=spec.name) for spec in ctx.registry.list_specs()]
    return AgentListResponse(default_agent=ctx.registry.default_agent, agents=agents)

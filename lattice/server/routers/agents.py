from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from lattice.protocol.models import (
    AgentInfo,
    AgentListResponse,
    ThreadAgentRequest,
    ThreadAgentResponse,
)
from lattice.server.context import AppContext
from lattice.server.deps import get_ctx
from lattice.server.services.agents import select_agent_for_thread, set_thread_agent

router = APIRouter()


@router.get("/agents", response_model=AgentListResponse)
async def api_list_agents(ctx: AppContext = Depends(get_ctx)) -> AgentListResponse:
    agents = [
        AgentInfo(id=spec.id, name=spec.name)
        for spec in ctx.registry.list_specs()
    ]
    return AgentListResponse(default_agent=ctx.registry.default_agent, agents=agents)


@router.get(
    "/sessions/{session_id}/threads/{thread_id}/agent",
    response_model=ThreadAgentResponse,
)
async def api_get_thread_agent(
    session_id: str,
    thread_id: str,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadAgentResponse:
    selection = select_agent_for_thread(ctx, session_id=session_id, thread_id=thread_id)
    return ThreadAgentResponse(
        agent=selection.agent_id,
        default_agent=selection.default_agent_id,
        is_default=selection.is_default,
        agent_name=selection.agent_name,
    )


@router.put(
    "/sessions/{session_id}/threads/{thread_id}/agent",
    response_model=ThreadAgentResponse,
)
async def api_set_thread_agent(
    session_id: str,
    thread_id: str,
    payload: ThreadAgentRequest,
    ctx: AppContext = Depends(get_ctx),
) -> ThreadAgentResponse:
    try:
        selection = set_thread_agent(
            ctx,
            session_id=session_id,
            thread_id=thread_id,
            requested=payload.agent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ThreadAgentResponse(
        agent=selection.agent_id,
        default_agent=selection.default_agent_id,
        is_default=selection.is_default,
        agent_name=selection.agent_name,
    )

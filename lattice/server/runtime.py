from __future__ import annotations

from lattice.agents.plugin import AgentPlugin
from lattice.server.context import AppContext
from lattice.server.services.agents import select_agent_for_thread
from lattice.server.services.models import resolve_default_model


def resolve_agent_plugin(ctx: AppContext, *, session_id: str, thread_id: str) -> tuple[str, AgentPlugin]:
    selection = select_agent_for_thread(ctx, session_id=session_id, thread_id=thread_id)
    return selection.agent_id, selection.plugin


__all__ = ["resolve_default_model", "resolve_agent_plugin"]

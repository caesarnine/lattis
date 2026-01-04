from __future__ import annotations

from dataclasses import dataclass

from lattice.agents.plugin import AgentPlugin
from lattice.server.context import AppContext


@dataclass(frozen=True)
class AgentSelection:
    agent_id: str
    plugin: AgentPlugin
    default_agent_id: str

    @property
    def is_default(self) -> bool:
        return self.agent_id == self.default_agent_id

    @property
    def agent_name(self) -> str:
        return self.plugin.name


def get_default_plugin(ctx: AppContext) -> AgentPlugin:
    return ctx.registry.agents[ctx.registry.default_agent]


def default_agent_selection(ctx: AppContext) -> AgentSelection:
    default_id = ctx.registry.default_agent
    return AgentSelection(
        agent_id=default_id,
        plugin=ctx.registry.agents[default_id],
        default_agent_id=default_id,
    )


def select_agent_for_thread(
    ctx: AppContext, *, session_id: str, thread_id: str
) -> AgentSelection:
    stored = ctx.store.get_thread_settings(session_id, thread_id).agent
    if stored:
        resolved = ctx.registry.resolve_id(stored, allow_fuzzy=False)
        if resolved:
            plugin = ctx.registry.agents[resolved]
            return AgentSelection(
                agent_id=resolved,
                plugin=plugin,
                default_agent_id=ctx.registry.default_agent,
            )
    return default_agent_selection(ctx)


def resolve_requested_agent(
    ctx: AppContext,
    requested: str,
    *,
    allow_fuzzy: bool = True,
) -> AgentSelection:
    resolved = ctx.registry.resolve_id(requested, allow_fuzzy=allow_fuzzy)
    if resolved is None:
        available = ", ".join(sorted({plugin.name for plugin in ctx.registry.agents.values()}))
        raise ValueError(f"Unknown or ambiguous agent '{requested}'. Available: {available}")
    plugin = ctx.registry.agents[resolved]
    return AgentSelection(
        agent_id=resolved,
        plugin=plugin,
        default_agent_id=ctx.registry.default_agent,
    )


def set_thread_agent(
    ctx: AppContext,
    *,
    session_id: str,
    thread_id: str,
    requested: str | None,
) -> AgentSelection:
    settings = ctx.store.get_thread_settings(session_id, thread_id)
    if requested is None or not requested.strip():
        settings.agent = None
        ctx.store.set_thread_settings(session_id, thread_id, settings)
        return default_agent_selection(ctx)

    selection = resolve_requested_agent(ctx, requested, allow_fuzzy=True)
    settings.agent = selection.agent_id
    ctx.store.set_thread_settings(session_id, thread_id, settings)
    return selection

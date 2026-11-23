from __future__ import annotations

from dataclasses import dataclass

from lattis.agents.plugin import AgentPlugin
from lattis.agents.registry import AgentRegistry
from lattis.domain.models import ThreadRecord, WorkspaceRecord


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


def get_default_plugin(registry: AgentRegistry) -> AgentPlugin:
    return registry.agents[registry.default_agent]


def default_agent_selection(
    registry: AgentRegistry,
    *,
    workspace: WorkspaceRecord | None = None,
) -> AgentSelection:
    ws_default = None
    if workspace and isinstance(workspace.settings, dict):
        raw = workspace.settings.get("default_agent")
        if isinstance(raw, str) and raw.strip():
            ws_default = registry.resolve_id(raw.strip(), allow_fuzzy=False)
    default_id = ws_default or registry.default_agent
    return AgentSelection(
        agent_id=default_id,
        plugin=registry.agents[default_id],
        default_agent_id=default_id,
    )


def select_agent_for_thread(
    registry: AgentRegistry,
    thread: ThreadRecord,
    *,
    workspace: WorkspaceRecord | None = None,
) -> AgentSelection:
    default_sel = default_agent_selection(registry, workspace=workspace)
    if thread.agent_id:
        resolved = registry.resolve_id(thread.agent_id, allow_fuzzy=False)
        if resolved:
            return AgentSelection(
                agent_id=resolved,
                plugin=registry.agents[resolved],
                default_agent_id=default_sel.agent_id,
            )
    return default_sel


def resolve_requested_agent(
    registry: AgentRegistry,
    requested: str,
    *,
    allow_fuzzy: bool = True,
    workspace: WorkspaceRecord | None = None,
) -> AgentSelection:
    resolved = registry.resolve_id(requested, allow_fuzzy=allow_fuzzy)
    if resolved is None:
        available = ", ".join(sorted({plugin.name for plugin in registry.agents.values()}))
        raise ValueError(f"Unknown or ambiguous agent '{requested}'. Available: {available}")
    default_sel = default_agent_selection(registry, workspace=workspace)
    return AgentSelection(
        agent_id=resolved,
        plugin=registry.agents[resolved],
        default_agent_id=default_sel.agent_id,
    )

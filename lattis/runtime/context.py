from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from lattis.agents.registry import AgentRegistry
from lattis.domain.models import DaemonStore
from lattis.runtime.events import EventBus
from lattis.settings.storage import DaemonConfig

if TYPE_CHECKING:
    from lattis.runtime.runs import RunManager


@dataclass
class AppContext:
    config: DaemonConfig
    store: DaemonStore
    registry: AgentRegistry
    bus: EventBus
    run_manager: RunManager
    auth_token: str | None = None
    cors_origins: tuple[str, ...] = field(default_factory=tuple)

    def plugin_data_dir(self, agent_id: str) -> Path:
        return self.config.plugin_data_dir(agent_id)

    def workspace_data_dir(self, workspace_id: str, agent_id: str) -> Path:
        return self.config.workspace_data_dir(workspace_id, agent_id)

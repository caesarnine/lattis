from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lattice.agents.registry import AgentRegistry
from lattice.domain.sessions import SessionStore
from lattice.settings.storage import StorageConfig


@dataclass(frozen=True)
class AppContext:
    config: StorageConfig
    store: SessionStore
    registry: AgentRegistry

    @property
    def workspace(self) -> Path:
        return self.config.workspace_dir

    @property
    def project_root(self) -> Path:
        return self.config.project_root

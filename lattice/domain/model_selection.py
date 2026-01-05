from __future__ import annotations

from dataclasses import dataclass

from lattice.agents.plugin import AgentPlugin
from lattice.domain.sessions import SessionStore
from lattice.settings.env import AGENT_MODEL, LATTICE_MODEL, first_env


@dataclass(frozen=True)
class ModelSelection:
    model: str
    default_model: str

    @property
    def is_default(self) -> bool:
        return self.model == self.default_model


def list_models(plugin: AgentPlugin) -> list[str]:
    if not plugin.list_models:
        return []
    try:
        return list(plugin.list_models())
    except Exception:
        return []


def resolve_default_model(plugin: AgentPlugin) -> str:
    configured = (plugin.default_model or "").strip()
    if configured:
        return configured
    env_model = first_env(AGENT_MODEL, LATTICE_MODEL)
    if env_model:
        return env_model
    models = list_models(plugin)
    return models[0] if models else ""


def select_session_model(
    store: SessionStore,
    *,
    session_id: str,
    plugin: AgentPlugin,
) -> ModelSelection:
    default_model = resolve_default_model(plugin)
    selected = store.get_session_model(session_id) or default_model
    return ModelSelection(model=selected, default_model=default_model)


def set_session_model(
    store: SessionStore,
    *,
    session_id: str,
    plugin: AgentPlugin,
    requested: str | None,
) -> ModelSelection:
    default_model = resolve_default_model(plugin)
    model = (requested or "").strip() if requested is not None else None
    if model:
        if plugin.validate_model:
            plugin.validate_model(model)
        store.set_session_model(session_id, model)
        return ModelSelection(model=model, default_model=default_model)

    store.set_session_model(session_id, None)
    return ModelSelection(model=default_model, default_model=default_model)

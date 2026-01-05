from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

from lattice.agents.plugin import AgentPlugin
from lattice.domain.sessions import SessionStore
from lattice.settings.env import AGENT_MODEL, LATTICE_MODEL, first_env

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSelection:
    model: str
    default_model: str

    @property
    def is_default(self) -> bool:
        return self.model == self.default_model


def _normalize_model_name(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


def _normalize_models(models: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for model in models:
        if model is None:
            continue
        value = _normalize_model_name(str(model))
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def list_models(plugin: AgentPlugin) -> list[str]:
    if not plugin.list_models:
        return []
    try:
        return _normalize_models(plugin.list_models())
    except Exception as exc:
        logger.warning("Failed to list models for agent '%s': %s", plugin.id, exc)
        return []


def resolve_default_model(plugin: AgentPlugin, *, models: Sequence[str] | None = None) -> str:
    configured = (plugin.default_model or "").strip()
    if configured:
        return configured
    env_model = first_env(AGENT_MODEL, LATTICE_MODEL)
    if env_model:
        return env_model
    models = list_models(plugin) if models is None else list(models)
    return models[0] if models else ""


def build_model_list(plugin: AgentPlugin) -> tuple[str, list[str]]:
    models = list_models(plugin)
    default_model = resolve_default_model(plugin, models=models)
    if default_model and default_model not in models:
        models = [default_model, *models]
    return default_model, models


def select_session_model(
    store: SessionStore,
    *,
    session_id: str,
    plugin: AgentPlugin,
) -> ModelSelection:
    default_model = resolve_default_model(plugin)
    stored = _normalize_model_name(store.get_session_model(session_id))
    if stored:
        if plugin.validate_model:
            try:
                plugin.validate_model(stored)
            except Exception as exc:
                logger.warning(
                    "Stored model '%s' is invalid for agent '%s': %s",
                    stored,
                    plugin.id,
                    exc,
                )
                store.set_session_model(session_id, None)
                stored = None
    selected = stored or default_model
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

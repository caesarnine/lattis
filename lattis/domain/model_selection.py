from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Sequence

from lattis.agents.plugin import AgentPlugin
from lattis.domain.models import DaemonStore, ThreadRecord, WorkspaceRecord
from lattis.settings.env import AGENT_MODEL, first_env

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


def resolve_default_model(
    plugin: AgentPlugin,
    *,
    workspace: WorkspaceRecord | None = None,
    models: Sequence[str] | None = None,
) -> str:
    if workspace and isinstance(workspace.settings, dict):
        ws_model = _normalize_model_name(
            str(workspace.settings["default_model"])
            if workspace.settings.get("default_model") is not None
            else None
        )
        if ws_model:
            valid = True
            if plugin.validate_model:
                try:
                    plugin.validate_model(ws_model)
                except Exception:
                    valid = False
            if valid:
                return ws_model

    configured = (plugin.default_model or "").strip()
    if configured:
        return configured
    env_model = first_env(AGENT_MODEL)
    if env_model:
        return env_model
    models = list_models(plugin) if models is None else list(models)
    return models[0] if models else ""


def build_model_list(
    plugin: AgentPlugin,
    *,
    workspace: WorkspaceRecord | None = None,
) -> tuple[str, list[str]]:
    models = list_models(plugin)
    default_model = resolve_default_model(plugin, workspace=workspace, models=models)
    if default_model and default_model not in models:
        models = [default_model, *models]
    return default_model, models


def validate_requested_model(plugin: AgentPlugin, requested: str | None) -> str | None:
    model = _normalize_model_name(requested)
    if not model:
        return None
    if plugin.validate_model:
        plugin.validate_model(model)
    return model


def select_thread_model(
    store: DaemonStore,
    thread: ThreadRecord,
    *,
    plugin: AgentPlugin,
    workspace: WorkspaceRecord | None = None,
) -> ModelSelection:
    default_model = resolve_default_model(plugin, workspace=workspace)
    stored = _normalize_model_name(thread.model)
    if stored:
        if plugin.validate_model:
            try:
                plugin.validate_model(stored)
            except Exception as exc:
                logger.warning(
                    "Stored model '%s' on thread '%s' is invalid for agent '%s': %s",
                    stored,
                    thread.id,
                    plugin.id,
                    exc,
                )
                store.update_thread(thread.id, model=None)
                stored = None
    selected = stored or default_model
    return ModelSelection(model=selected, default_model=default_model)

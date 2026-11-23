from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Sequence

from lattis.agents.plugin import (
    AgentPlugin,
    AgentRunContext,
    CreateDepsFn,
    EmitToolOutputFn,
    GetStateFn,
    NotifyStateChangedFn,
    PluginStateContext,
    RunCompleteFn,
    list_known_models,
    normalize_plugin,
)

__all__ = [
    "AgentPlugin",
    "AgentRunContext",
    "CreateDepsFn",
    "EmitToolOutputFn",
    "GetStateFn",
    "NotifyStateChangedFn",
    "PluginStateContext",
    "RunCompleteFn",
    "list_known_models",
    "plugin_from",
]


def plugin_from(
    obj: Any,
    *,
    id: str | None = None,
    name: str | None = None,
    create_deps: CreateDepsFn | None = None,
    default_model: str | None = None,
    list_models: Callable[[], Sequence[str]] | None = None,
    validate_model: Callable[[str], None] | None = None,
    on_complete: RunCompleteFn | None = None,
    get_state: GetStateFn | None = None,
) -> AgentPlugin:
    """
    Build an AgentPlugin from a pydantic-ai Agent or factory.

    Keeps simple integrations frictionless while allowing full customization.
    """
    plugin = normalize_plugin(obj, id=id, name=name, create_deps=create_deps)
    if default_model is not None:
        plugin = replace(plugin, default_model=default_model)
    if list_models is not None:
        plugin = replace(plugin, list_models=list_models)
    if validate_model is not None:
        plugin = replace(plugin, validate_model=validate_model)
    if on_complete is not None:
        plugin = replace(plugin, on_complete=on_complete)
    if get_state is not None:
        plugin = replace(plugin, get_state=get_state)
    return plugin

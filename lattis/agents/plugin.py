from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Sequence, get_args

from pydantic_ai import Agent
from pydantic_ai.models import KnownModelName, infer_model
from pydantic_ai.ui.vercel_ai.request_types import RequestData

from lattis.settings.env import AGENT_PLUGIN, read_env

DEFAULT_PLUGIN_SPEC = "lattis.agents.builtins.assistant:plugin"


@dataclass(frozen=True)
class AgentRunContext:
    session_id: str
    thread_id: str
    model: str
    workspace: Path
    project_root: Path
    run_input: RequestData


CreateAgentFn = Callable[[str], Agent[Any, Any]]
CreateDepsFn = Callable[[AgentRunContext], Any]
RunCompleteFn = Callable[[AgentRunContext, Any], None]


@dataclass(frozen=True)
class AgentPlugin:
    """
    Server integration layer for a pydantic-ai Agent.

    This is intentionally small: create an Agent (optionally per-model), optionally
    create a deps object for each run, and optionally hook completion.
    """

    id: str
    name: str
    create_agent: CreateAgentFn
    create_deps: CreateDepsFn | None = None
    default_model: str | None = None
    list_models: Callable[[], Sequence[str]] | None = None
    validate_model: Callable[[str], None] | None = None
    on_complete: RunCompleteFn | None = None


def _load_symbol(spec: str) -> Any:
    """
    Load `module:attr` and return the resolved attribute.
    """
    if ":" not in spec:
        raise ValueError(f"Invalid spec '{spec}'. Expected 'module:attribute'.")
    module_name, attr = spec.split(":", 1)
    if not module_name or not attr:
        raise ValueError(f"Invalid spec '{spec}'. Expected 'module:attribute'.")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, attr)
    except AttributeError as exc:  # pragma: no cover
        raise AttributeError(f"Module '{module_name}' has no attribute '{attr}'") from exc


def _callable_arity(fn: Callable[..., Any]) -> int | None:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    count = 0
    for param in sig.parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            return None
        count += 1
    return count


def _wrap_agent_factory(obj: Any, *, name: str) -> CreateAgentFn:
    if isinstance(obj, Agent):
        return lambda model: obj
    if callable(obj):
        arity = _callable_arity(obj)
        if arity == 0:
            created = obj()
            if not isinstance(created, Agent):
                raise TypeError(f"{name} factory returned {type(created)!r}, expected pydantic_ai.Agent")
            return lambda model: created
        if arity is not None and arity > 1:
            raise TypeError(f"{name} factory must accept 0 or 1 arguments, got {arity}")
        return lambda model: obj(model)
    raise TypeError(f"Unsupported agent spec type: {type(obj)!r}")


def _slugify(value: str) -> str:
    value = value.strip().casefold()
    out: list[str] = []
    prev_dash = False
    for ch in value:
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
            continue
        if not prev_dash:
            out.append("-")
            prev_dash = True
    slug = "".join(out).strip("-")
    return slug or "agent"


def normalize_plugin(
    obj: Any,
    *,
    id: str | None = None,
    name: str | None = None,
    create_deps: CreateDepsFn | None = None,
) -> AgentPlugin:
    if isinstance(obj, AgentPlugin):
        plugin = obj
    else:
        plugin_name = name or getattr(obj, "__name__", None) or "Agent"
        plugin_id = id or _slugify(plugin_name)
        create_agent = _wrap_agent_factory(obj, name=plugin_name)
        plugin = AgentPlugin(id=plugin_id, name=plugin_name, create_agent=create_agent)

    if name:
        plugin = replace(plugin, name=name)
    if id:
        plugin = replace(plugin, id=id)
    if create_deps is not None:
        plugin = replace(plugin, create_deps=create_deps)
    return plugin


def load_plugin(
    *,
    plugin_spec: str | None = None,
    id: str | None = None,
    name: str | None = None,
    deps_spec: str | None = None,
) -> AgentPlugin:
    env_spec = read_env(AGENT_PLUGIN) or ""
    resolved_spec = (plugin_spec or "").strip() or env_spec or DEFAULT_PLUGIN_SPEC
    obj = _load_symbol(resolved_spec)

    create_deps: CreateDepsFn | None = None
    if deps_spec:
        deps_obj = _load_symbol(deps_spec)
        if not callable(deps_obj):
            raise TypeError(f"Deps factory must be callable, got {type(deps_obj)!r}")
        create_deps = deps_obj

    plugin = normalize_plugin(obj, id=id, name=name, create_deps=create_deps)
    if plugin.validate_model is None:
        plugin = replace(plugin, validate_model=infer_model)
    if plugin.list_models is None:
        plugin = replace(
            plugin,
            list_models=lambda: list_known_models(default_model=plugin.default_model),
        )
    return plugin


@lru_cache(maxsize=1)
def list_known_models(*, default_model: str | None = None) -> tuple[str, ...]:
    literal = getattr(KnownModelName, "__value__", None)
    models: list[str] = []
    if literal is not None:
        try:
            models = list(get_args(literal))
        except TypeError:
            models = []

    if default_model:
        if default_model in models:
            models = [default_model, *[item for item in models if item != default_model]]
        else:
            models.insert(0, default_model)

    return tuple(models)

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import pkgutil
from dataclasses import dataclass
from typing import Iterable

from lattis.agents.plugin import AgentPlugin, load_plugin
from lattis.settings.env import AGENT_DEFAULT, AGENT_PLUGINS, read_env

logger = logging.getLogger(__name__)

AGENT_ENTRYPOINT_GROUP = "lattis.agents"
DEFAULT_AGENT_ID = "assistant"


@dataclass(frozen=True)
class AgentSpec:
    id: str
    name: str


@dataclass(frozen=True)
class AgentRegistry:
    agents: dict[str, AgentPlugin]
    default_agent: str

    def list_specs(self) -> list[AgentSpec]:
        items = sorted(self.agents.items(), key=lambda item: (item[1].name.casefold(), item[0]))
        return [AgentSpec(id=agent_id, name=plugin.name) for agent_id, plugin in items]

    def get(self, agent_id: str) -> AgentPlugin | None:
        return self.agents.get(agent_id)

    def resolve_id(self, requested: str, *, allow_fuzzy: bool = True) -> str | None:
        return _resolve_agent_id(
            self.agents,
            requested,
            allow_fuzzy=allow_fuzzy,
            allow_id_prefix=allow_fuzzy,
        )


def _split_specs(value: str) -> list[str]:
    raw = [part.strip() for part in value.replace("\n", ",").split(",")]
    return [spec for spec in raw if spec]


def _resolve_agent_id(
    agents: dict[str, AgentPlugin],
    requested: str,
    *,
    allow_fuzzy: bool = True,
    allow_id_prefix: bool = True,
) -> str | None:
    value = requested.strip()
    if not value:
        return None

    if value in agents:
        return value

    needle = value.casefold()
    by_name = [agent_id for agent_id, plugin in agents.items() if plugin.name.casefold() == needle]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        return None

    if not allow_fuzzy:
        return None

    prefix_by_name = [
        agent_id for agent_id, plugin in agents.items() if plugin.name.casefold().startswith(needle)
    ]
    if len(prefix_by_name) == 1:
        return prefix_by_name[0]

    if allow_id_prefix:
        prefix_by_id = [agent_id for agent_id in agents.keys() if agent_id.casefold().startswith(needle)]
        if len(prefix_by_id) == 1:
            return prefix_by_id[0]

    return None


def discover_builtin_agent_specs() -> list[str]:
    try:
        pkg = importlib.import_module("lattis.agents.builtins")
    except Exception as exc:
        logger.debug("Failed to import builtin agents package.", exc_info=exc)
        return []

    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        return []

    specs: list[str] = []
    for module_info in pkgutil.iter_modules(pkg_path, prefix=f"{pkg.__name__}."):
        module_name = module_info.name
        leaf = module_name.rsplit(".", 1)[-1]
        if leaf.startswith("_"):
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            logger.debug("Failed to import builtin agent module %s.", module_name, exc_info=exc)
            continue
        if getattr(module, "plugin", None) is None:
            continue
        specs.append(f"{module_name}:plugin")

    specs = sorted(set(specs))
    return specs


def discover_entrypoint_specs(*, group: str = AGENT_ENTRYPOINT_GROUP) -> list[tuple[str, str]]:
    """
    Discover third-party agents registered via Python entry points.

    Returns a list of (entrypoint_name, module_spec) tuples.
    """
    try:
        points = importlib.metadata.entry_points(group=group)
    except TypeError:  # pragma: no cover - older metadata API
        points = importlib.metadata.entry_points().get(group, [])
    out: list[tuple[str, str]] = []
    for ep in points:
        name = getattr(ep, "name", None)
        value = getattr(ep, "value", None)
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        out.append((name.strip(), value.strip()))
    return sorted(out, key=lambda item: item[0])


def load_registry(
    *,
    plugin_specs: Iterable[str] | None = None,
    default_spec: str | None = None,
) -> AgentRegistry:
    extra_specs: list[str] = []
    if plugin_specs is not None:
        extra_specs = [spec.strip() for spec in plugin_specs if spec and spec.strip()]
    else:
        env_list = read_env(AGENT_PLUGINS)
        if env_list:
            extra_specs = _split_specs(env_list)

    builtin_specs = discover_builtin_agent_specs()
    entrypoint_specs = discover_entrypoint_specs()

    agents: dict[str, AgentPlugin] = {}

    # Built-ins (source tree and/or installed)
    for spec in builtin_specs:
        try:
            plugin = load_plugin(plugin_spec=spec)
        except Exception as exc:
            logger.debug("Failed to load builtin agent plugin %s.", spec, exc_info=exc)
            continue
        agents[plugin.id] = plugin

    # Third-party entry points
    for ep_name, ep_spec in entrypoint_specs:
        try:
            plugin = load_plugin(plugin_spec=ep_spec, id=ep_name)
        except Exception as exc:
            logger.debug("Failed to load entry point agent %s (%s).", ep_name, ep_spec, exc_info=exc)
            continue
        agents[plugin.id] = plugin

    # Explicit extras override built-ins/entry points by id.
    for spec in extra_specs:
        try:
            plugin = load_plugin(plugin_spec=spec)
        except Exception as exc:
            logger.debug("Failed to load agent plugin %s.", spec, exc_info=exc)
            continue
        agents[plugin.id] = plugin

    if not agents:
        fallback = load_plugin()
        agents[fallback.id] = fallback

    env_default = read_env(AGENT_DEFAULT) or ""
    configured_default = (default_spec or "").strip() or env_default
    resolved_default = (
        _resolve_agent_id(
            agents,
            configured_default,
            allow_fuzzy=True,
            allow_id_prefix=False,
        )
        if configured_default
        else None
    )
    if not resolved_default:
        resolved_default = DEFAULT_AGENT_ID if DEFAULT_AGENT_ID in agents else sorted(agents.keys())[0]

    return AgentRegistry(agents=agents, default_agent=resolved_default)

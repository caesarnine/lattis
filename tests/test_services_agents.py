from __future__ import annotations

import pytest

from lattis.agents.plugin import AgentPlugin
from lattis.agents.registry import AgentRegistry
from lattis.domain.agents import (
    resolve_requested_agent,
    select_agent_for_thread,
)
from lattis.domain.models import ThreadRecord, WorkspaceRecord


def _make_plugin(agent_id: str, name: str) -> AgentPlugin:
    return AgentPlugin(id=agent_id, name=name, create_agent=lambda model: object())


@pytest.fixture()
def registry():
    default_plugin = _make_plugin("alpha", "Alpha")
    other_plugin = _make_plugin("beta", "Beta Agent")
    return AgentRegistry(
        agents={"alpha": default_plugin, "beta": other_plugin},
        default_agent="alpha",
    )


def _thread(agent_id: str | None = None) -> ThreadRecord:
    return ThreadRecord(
        id="thr-1",
        workspace_id="ws-1",
        title="",
        agent_id=agent_id,
        model=None,
        status="idle",
    )


def test_select_agent_for_thread_uses_stored_id(registry) -> None:
    selection = select_agent_for_thread(registry, _thread("beta"))
    assert selection.agent_id == "beta"
    assert selection.agent_name == "Beta Agent"
    assert selection.is_default is False


def test_select_agent_for_thread_falls_back_when_not_exact(registry) -> None:
    selection = select_agent_for_thread(registry, _thread("Beta"))
    assert selection.agent_id == "alpha"
    assert selection.is_default is True


def test_select_agent_uses_workspace_default(registry) -> None:
    ws = WorkspaceRecord(
        id="ws-1",
        name="Proj",
        root_path="/tmp/proj",
        kind="project",
        settings={"default_agent": "beta"},
    )
    selection = select_agent_for_thread(registry, _thread(None), workspace=ws)
    assert selection.agent_id == "beta"
    assert selection.is_default is True


def test_resolve_requested_agent_allows_fuzzy_by_name(registry) -> None:
    selection = resolve_requested_agent(registry, "be")
    assert selection.agent_id == "beta"


def test_resolve_requested_agent_unknown_raises(registry) -> None:
    with pytest.raises(ValueError):
        resolve_requested_agent(registry, "unknown")

from __future__ import annotations

import pytest

from lattice.agents.plugin import AgentPlugin
from lattice.agents.registry import AgentRegistry
from lattice.config import StorageConfig
from lattice.core.session import ThreadSettings
from lattice.server.context import AppContext
from lattice.server.services.agents import (
    resolve_requested_agent,
    select_agent_for_thread,
    set_thread_agent,
)


class FakeStore:
    def __init__(self) -> None:
        self._thread_settings: dict[tuple[str, str], ThreadSettings] = {}

    def get_thread_settings(self, session_id: str, thread_id: str) -> ThreadSettings:
        return self._thread_settings.get((session_id, thread_id), ThreadSettings())

    def set_thread_settings(self, session_id: str, thread_id: str, settings: ThreadSettings) -> None:
        self._thread_settings[(session_id, thread_id)] = settings

    def get_session_model(self, session_id: str) -> str | None:
        return None

    def set_session_model(self, session_id: str, model: str | None) -> None:
        return None


def _make_plugin(agent_id: str, name: str) -> AgentPlugin:
    return AgentPlugin(id=agent_id, name=name, create_agent=lambda model: object())


@pytest.fixture()
def agent_ctx(tmp_path):
    config = StorageConfig(
        data_dir=tmp_path,
        db_path=tmp_path / "lattice.db",
        session_id_path=tmp_path / "session_id",
        workspace_dir=tmp_path / "workspace",
        project_root=tmp_path,
        workspace_mode="local",
    )
    store = FakeStore()
    default_plugin = _make_plugin("alpha", "Alpha")
    other_plugin = _make_plugin("beta", "Beta Agent")
    ctx = AppContext(
        config=config,
        store=store,
        workspace=tmp_path,
        project_root=tmp_path,
        registry=AgentRegistry(
            agents={"alpha": default_plugin, "beta": other_plugin},
            default_agent="alpha",
        ),
    )
    return ctx, store


def test_select_agent_for_thread_uses_stored_id(agent_ctx) -> None:
    ctx, store = agent_ctx
    store.set_thread_settings("s1", "t1", ThreadSettings(agent="beta"))
    selection = select_agent_for_thread(ctx, session_id="s1", thread_id="t1")
    assert selection.agent_id == "beta"
    assert selection.agent_name == "Beta Agent"
    assert selection.is_default is False


def test_select_agent_for_thread_falls_back_when_not_exact(agent_ctx) -> None:
    ctx, store = agent_ctx
    store.set_thread_settings("s1", "t1", ThreadSettings(agent="Beta"))
    selection = select_agent_for_thread(ctx, session_id="s1", thread_id="t1")
    assert selection.agent_id == "alpha"
    assert selection.is_default is True


def test_set_thread_agent_resets_to_default(agent_ctx) -> None:
    ctx, store = agent_ctx
    selection = set_thread_agent(ctx, session_id="s1", thread_id="t1", requested=None)
    assert selection.agent_id == "alpha"
    assert selection.is_default is True
    settings = store.get_thread_settings("s1", "t1")
    assert settings.agent is None


def test_set_thread_agent_unknown_raises(agent_ctx) -> None:
    ctx, _ = agent_ctx
    with pytest.raises(ValueError):
        set_thread_agent(ctx, session_id="s1", thread_id="t1", requested="unknown")


def test_resolve_requested_agent_allows_fuzzy_by_name(agent_ctx) -> None:
    ctx, _ = agent_ctx
    selection = resolve_requested_agent(ctx, "be")
    assert selection.agent_id == "beta"

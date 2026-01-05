from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from lattice.agents.plugin import AgentPlugin
from lattice.domain.model_selection import (
    resolve_default_model,
    select_session_model,
    set_session_model,
)


class FakeStore:
    def __init__(self) -> None:
        self._session_models: dict[str, str | None] = {}

    def get_session_model(self, session_id: str) -> str | None:
        return self._session_models.get(session_id)

    def set_session_model(self, session_id: str, model: str | None) -> None:
        self._session_models[session_id] = model


def _make_plugin(
    *,
    default_model: str | None = None,
    list_models=None,
    validate_model=None,
) -> AgentPlugin:
    return AgentPlugin(
        id="agent",
        name="Agent",
        create_agent=lambda model: object(),
        default_model=default_model,
        list_models=list_models,
        validate_model=validate_model,
    )


@pytest.fixture()
def store():
    return FakeStore()


def test_resolve_default_model_prefers_plugin_default() -> None:
    plugin = _make_plugin(default_model="plugin-model", list_models=lambda: ["model-a"])
    with patch.dict(os.environ, {"AGENT_MODEL": "env-model"}, clear=True):
        assert resolve_default_model(plugin) == "plugin-model"


def test_resolve_default_model_uses_env() -> None:
    plugin = _make_plugin(default_model=None, list_models=lambda: ["model-a"])
    with patch.dict(os.environ, {"AGENT_MODEL": "env-model"}, clear=True):
        assert resolve_default_model(plugin) == "env-model"


def test_resolve_default_model_falls_back_to_list() -> None:
    plugin = _make_plugin(default_model=None, list_models=lambda: ["first", "second"])
    with patch.dict(os.environ, {}, clear=True):
        assert resolve_default_model(plugin) == "first"


def test_select_session_model_prefers_store(store) -> None:
    plugin = _make_plugin(default_model="default-model", list_models=lambda: ["default-model"])
    store.set_session_model("s1", "custom-model")
    selection = select_session_model(store, session_id="s1", plugin=plugin)
    assert selection.model == "custom-model"
    assert selection.default_model == "default-model"
    assert selection.is_default is False


def test_set_session_model_resets_to_default(store) -> None:
    plugin = _make_plugin(default_model="default-model", list_models=lambda: ["default-model"])
    selection = set_session_model(store, session_id="s1", plugin=plugin, requested=None)
    assert selection.model == "default-model"
    assert selection.is_default is True
    assert store.get_session_model("s1") is None


def test_set_session_model_calls_validator(store) -> None:
    def validate_model(value: str) -> None:
        if value != "ok":
            raise ValueError("bad model")

    plugin = _make_plugin(
        default_model="default-model",
        list_models=lambda: ["default-model"],
        validate_model=validate_model,
    )
    with pytest.raises(ValueError):
        set_session_model(store, session_id="s1", plugin=plugin, requested="bad")

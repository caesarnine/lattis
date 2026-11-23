from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from lattis.agents.plugin import AgentPlugin
from lattis.domain.model_selection import (
    resolve_default_model,
    select_thread_model,
    validate_requested_model,
)
from lattis.domain.models import ThreadRecord


class FakeStore:
    def __init__(self, thread: ThreadRecord) -> None:
        self.thread = thread

    def update_thread(self, thread_id: str, **kwargs) -> ThreadRecord:
        assert thread_id == self.thread.id
        if "model" in kwargs:
            self.thread.model = kwargs["model"]
        return self.thread


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


def _thread(model: str | None = None) -> ThreadRecord:
    return ThreadRecord(
        id="thr-1",
        workspace_id="ws-1",
        title="",
        agent_id="agent",
        model=model,
        status="idle",
    )


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


def test_select_thread_model_prefers_thread_value() -> None:
    plugin = _make_plugin(default_model="default-model", list_models=lambda: ["default-model"])
    thread = _thread("custom-model")
    store = FakeStore(thread)
    selection = select_thread_model(store, thread, plugin=plugin)
    assert selection.model == "custom-model"
    assert selection.default_model == "default-model"
    assert selection.is_default is False


def test_select_thread_model_invalid_stored_resets() -> None:
    def validate_model(value: str) -> None:
        if value != "valid-model":
            raise ValueError("bad model")

    plugin = _make_plugin(
        default_model="valid-model",
        list_models=lambda: ["valid-model"],
        validate_model=validate_model,
    )
    thread = _thread("bad-model")
    store = FakeStore(thread)
    selection = select_thread_model(store, thread, plugin=plugin)
    assert selection.model == "valid-model"
    assert selection.is_default is True
    assert store.thread.model is None


def test_validate_requested_model_calls_validator() -> None:
    def validate_model(value: str) -> None:
        if value != "ok":
            raise ValueError("bad model")

    plugin = _make_plugin(default_model="ok", validate_model=validate_model)
    assert validate_requested_model(plugin, "ok") == "ok"
    assert validate_requested_model(plugin, "  ") is None
    with pytest.raises(ValueError):
        validate_requested_model(plugin, "bad")

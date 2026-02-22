from __future__ import annotations

from pathlib import Path

import pytest

from lattis.domain.channels import (
    ChannelBindingConflictError,
    list_thread_channel_bindings,
    resolve_channel_thread_binding,
)
from lattis.storage.sqlite import SQLiteSessionStore


def test_resolve_channel_thread_binding_is_sticky(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "lattis.db")

    binding, created = resolve_channel_thread_binding(
        store,
        session_id="s1",
        channel="telegram",
        external_conversation_id="12345",
        external_user_id="42",
    )
    assert created is True
    assert store.thread_exists("s1", binding.thread_id)

    reused, created = resolve_channel_thread_binding(
        store,
        session_id="s1",
        channel="telegram",
        external_conversation_id="12345",
        external_user_id="42",
    )
    assert created is False
    assert reused.thread_id == binding.thread_id

    bindings = list_thread_channel_bindings(
        store,
        session_id="s1",
        thread_id=binding.thread_id,
    )
    assert len(bindings) == 1
    assert bindings[0].channel == "telegram"
    assert bindings[0].external_conversation_id == "12345"


def test_resolve_channel_thread_binding_conflict_between_sessions(tmp_path: Path) -> None:
    store = SQLiteSessionStore(tmp_path / "lattis.db")
    resolve_channel_thread_binding(
        store,
        session_id="s1",
        channel="telegram",
        external_conversation_id="12345",
    )

    with pytest.raises(ChannelBindingConflictError):
        resolve_channel_thread_binding(
            store,
            session_id="s2",
            channel="telegram",
            external_conversation_id="12345",
        )

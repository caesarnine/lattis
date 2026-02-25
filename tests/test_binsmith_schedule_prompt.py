from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lattis.agents.builtins.binsmith import _format_schedules_for_system_prompt
from lattis.domain.schedules import SCHEDULE_TRIGGER_ONCE, create_schedule
from lattis.storage.sqlite import SQLiteSessionStore


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteSessionStore:
    path = tmp_path / "lattis.db"
    data_store = SQLiteSessionStore(path)
    data_store.save_thread("s1", "t1", messages=[])
    return data_store


def _extract_json_block(text: str) -> str:
    start = text.index("<schedules")
    start = text.index("\n", start) + 1
    end = text.index("\n</schedules>", start)
    return text[start:end]


def test_binsmith_instructions_include_schedules_json(store: SQLiteSessionStore) -> None:
    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        name="one-shot",
        prompt="Do the thing.",
        trigger_type=SCHEDULE_TRIGGER_ONCE,
        run_at=time.time() + 60,
    )

    section = _format_schedules_for_system_prompt(
        store=store,
        session_id="s1",
        thread_id="t1",
        limit=10,
    )

    assert "## Thread Schedules" in section
    assert "<schedules" in section

    raw = _extract_json_block(section)
    payload = json.loads(raw)
    assert isinstance(payload, list)
    names = {item.get("name") for item in payload}
    assert "heartbeat" in names
    assert "one-shot" in names


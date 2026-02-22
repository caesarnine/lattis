from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

from lattis.agents.registry import load_registry
from lattis.channels import ChannelAdapterRegistry
from lattis.domain.schedules import SCHEDULE_STATUS_DONE, SCHEDULE_STATUS_PENDING, create_schedule, list_schedules
from lattis.runtime.context import AppContext
from lattis.scheduler import SchedulerConfig, SchedulerWorker
from lattis.settings.storage import load_storage_config
from lattis.storage.sqlite import SQLiteSessionStore


def _load_latest_schedule_run(db_path: Path) -> tuple[str, int, str | None]:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT status, notified_count, result_text
            FROM schedule_runs
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1]), str(row[2]) if row[2] is not None else None


def _load_latest_outbox_status(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT status
            FROM notification_outbox
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    assert row is not None
    return str(row[0])


def test_scheduler_worker_keeps_thread_clean_without_notification(tmp_path: Path) -> None:
    config = load_storage_config(project_root=tmp_path)
    store = SQLiteSessionStore(config.db_path)
    store.save_thread("s1", "t1", messages=[])
    store.set_session_model("s1", "test")
    registry = load_registry(default_spec="assistant")
    ctx = AppContext(config=config, store=store, registry=registry)

    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Remind me to stand up.",
        due_at=time.time() - 5,
    )

    worker = SchedulerWorker(ctx=ctx, config=SchedulerConfig(run_once=True, claim_limit=5))

    async def fake_run_schedule(_schedule, *, trigger_prompt: str) -> tuple[str, list[str]]:
        assert "Scheduled background task trigger." in trigger_prompt
        return "checked inbox; nothing urgent", []

    worker._run_schedule = fake_run_schedule  # type: ignore[assignment]

    async def run_once() -> None:
        processed = await worker.run_once()
        assert processed == 1
        await worker.close()

    asyncio.run(run_once())

    schedules = list_schedules(
        store,
        session_id="s1",
        thread_id="t1",
        include_terminal=True,
        limit=20,
    )
    assert schedules[0].status == SCHEDULE_STATUS_DONE

    thread_state = store.load_thread("s1", "t1")
    assert thread_state is not None
    assert thread_state.messages == []

    status, notified_count, result_text = _load_latest_schedule_run(config.db_path)
    assert status == "done"
    assert notified_count == 0
    assert result_text == "checked inbox; nothing urgent"


def test_scheduler_worker_reschedules_recurring_task(tmp_path: Path) -> None:
    config = load_storage_config(project_root=tmp_path)
    store = SQLiteSessionStore(config.db_path)
    store.save_thread("s1", "t1", messages=[])
    store.set_session_model("s1", "test")
    registry = load_registry(default_spec="assistant")
    ctx = AppContext(config=config, store=store, registry=registry)

    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Recurring reminder.",
        due_at=time.time() - 120,
        interval_seconds=60,
    )

    worker = SchedulerWorker(ctx=ctx, config=SchedulerConfig(run_once=True, claim_limit=5))

    async def fake_run_schedule(_schedule, *, trigger_prompt: str) -> tuple[str, list[str]]:
        assert "Task request: Recurring reminder." in trigger_prompt
        return "checked inbox", ["Urgent email: production issue in Europe."]

    worker._run_schedule = fake_run_schedule  # type: ignore[assignment]

    async def run_once() -> None:
        processed = await worker.run_once()
        assert processed == 1
        await worker.close()

    asyncio.run(run_once())

    schedules = list_schedules(
        store,
        session_id="s1",
        thread_id="t1",
        include_terminal=True,
        limit=20,
    )
    assert schedules[0].status == SCHEDULE_STATUS_PENDING
    assert schedules[0].due_at > time.time()

    thread_state = store.load_thread("s1", "t1")
    assert thread_state is not None
    assert len(thread_state.messages) == 1
    response = thread_state.messages[0]
    assert getattr(response, "kind", None) == "response"
    parts = getattr(response, "parts", [])
    assert parts and getattr(parts[0], "content", None) == "Urgent email: production issue in Europe."

    status, notified_count, result_text = _load_latest_schedule_run(config.db_path)
    assert status == "done"
    assert notified_count == 1
    assert result_text == "checked inbox"


def test_scheduler_worker_dispatches_outbox_notifications(tmp_path: Path) -> None:
    config = load_storage_config(project_root=tmp_path)
    store = SQLiteSessionStore(config.db_path)
    store.save_thread("s1", "t1", messages=[])
    store.set_session_model("s1", "test")
    store.upsert_channel_binding_record(
        binding_id="bind-1",
        session_id="s1",
        thread_id="t1",
        channel="telegram",
        external_conversation_id="12345",
        external_user_id=None,
        metadata_json=None,
        updated_at=time.time(),
    )

    registry = load_registry(default_spec="assistant")
    ctx = AppContext(config=config, store=store, registry=registry)

    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Send proactive update.",
        due_at=time.time() - 5,
    )

    class _FakeAdapter:
        def __init__(self) -> None:
            self.delivered: list[str] = []

        async def send_text(self, *, external_conversation_id: str, text: str) -> None:
            self.delivered.append(f"telegram:{external_conversation_id}:{text}")

        async def close(self) -> None:
            return None

    fake_adapter = _FakeAdapter()
    registry = ChannelAdapterRegistry()
    registry.register_instance(channel="telegram", adapter=fake_adapter)

    worker = SchedulerWorker(
        ctx=ctx,
        config=SchedulerConfig(run_once=True, claim_limit=5),
        channel_adapters=registry,
    )

    async def fake_run_schedule(_schedule, *, trigger_prompt: str) -> tuple[str, list[str]]:
        assert "Task request: Send proactive update." in trigger_prompt
        return "done", ["Heads up: proactive check complete."]

    worker._run_schedule = fake_run_schedule  # type: ignore[assignment]

    async def run_once() -> None:
        processed = await worker.run_once()
        assert processed == 2  # 1 schedule + 1 outbox delivery pass
        await worker.close()

    asyncio.run(run_once())

    assert fake_adapter.delivered == ["telegram:12345:Heads up: proactive check complete."]
    assert _load_latest_outbox_status(config.db_path) == "sent"

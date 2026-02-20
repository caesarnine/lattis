from __future__ import annotations

import asyncio
import time
from pathlib import Path

from lattis.agents.registry import load_registry
from lattis.domain.schedules import SCHEDULE_STATUS_DONE, SCHEDULE_STATUS_PENDING, create_schedule, list_schedules
from lattis.runtime.context import AppContext
from lattis.scheduler import SchedulerConfig, SchedulerWorker
from lattis.settings.storage import load_storage_config
from lattis.storage.sqlite import SQLiteSessionStore


def test_scheduler_worker_executes_due_schedule(tmp_path: Path) -> None:
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
    assert thread_state.messages


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

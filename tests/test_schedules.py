from __future__ import annotations

import time
from pathlib import Path

import pytest

from lattis.domain.schedules import (
    SCHEDULE_RUN_STATUS_DONE,
    SCHEDULE_RUN_STATUS_RUNNING,
    SCHEDULE_STATUS_CANCELED,
    SCHEDULE_STATUS_DONE,
    SCHEDULE_STATUS_PENDING,
    SCHEDULE_STATUS_RUNNING,
    ScheduleStateConflictError,
    ScheduleValidationError,
    cancel_schedule,
    claim_due_schedules,
    complete_schedule_run,
    create_schedule,
    create_schedule_run,
    fail_schedule_run,
    finish_schedule_run,
    get_schedule_state,
    list_schedules,
    next_due_for_interval,
    parse_due_at,
    set_schedule_state,
    update_schedule,
)
from lattis.storage.sqlite import SQLiteSessionStore


@pytest.fixture()
def store(tmp_path: Path) -> SQLiteSessionStore:
    path = tmp_path / "lattis.db"
    data_store = SQLiteSessionStore(path)
    data_store.save_thread("s1", "t1", messages=[])
    return data_store


def test_parse_due_at_requires_timezone() -> None:
    with pytest.raises(ScheduleValidationError):
        parse_due_at("2026-03-01T09:00:00")
    assert parse_due_at("2026-03-01T09:00:00Z") > 0


def test_next_due_for_interval_advances_past_now() -> None:
    now = 1_000.0
    assert next_due_for_interval(current_due_at=900.0, interval_seconds=60, now=now) == 1_020.0


def test_create_update_list_cancel_schedule(store: SQLiteSessionStore) -> None:
    due_at = time.time() + 120
    created = create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Take a break",
        due_at=due_at,
    )
    assert created.status == SCHEDULE_STATUS_PENDING

    listed = list_schedules(store, session_id="s1", thread_id="t1")
    assert len(listed) == 1
    assert listed[0].schedule_id == created.schedule_id

    updated = update_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id=created.schedule_id,
        prompt="Take a longer break",
        interval_seconds=600,
    )
    assert updated.prompt == "Take a longer break"
    assert updated.interval_seconds == 600

    canceled = cancel_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id=created.schedule_id,
    )
    assert canceled.status == SCHEDULE_STATUS_CANCELED


def test_claim_and_complete_one_shot_schedule(store: SQLiteSessionStore) -> None:
    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="One-shot task",
        due_at=time.time() - 5,
    )
    claimed = claim_due_schedules(store, limit=5, lease_seconds=30)
    assert len(claimed) == 1
    assert claimed[0].status == SCHEDULE_STATUS_RUNNING

    completed = complete_schedule_run(store, schedule=claimed[0], completed_at=time.time())
    assert completed is not None
    assert completed.status == SCHEDULE_STATUS_DONE
    assert completed.last_run_at is not None


def test_complete_recurring_schedule_reschedules(store: SQLiteSessionStore) -> None:
    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Recurring task",
        due_at=time.time() - 600,
        interval_seconds=120,
    )
    claimed = claim_due_schedules(store, limit=5, lease_seconds=30)
    assert len(claimed) == 1
    completed_at = time.time()
    completed = complete_schedule_run(store, schedule=claimed[0], completed_at=completed_at)
    assert completed is not None
    assert completed.status == SCHEDULE_STATUS_PENDING
    assert completed.due_at > completed_at
    assert completed.due_at - completed_at <= 120


def test_fail_schedule_run_retries_with_error(store: SQLiteSessionStore) -> None:
    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Failing task",
        due_at=time.time() - 30,
    )
    claimed = claim_due_schedules(store, limit=5, lease_seconds=30)
    assert len(claimed) == 1
    failed_at = time.time()
    failed = fail_schedule_run(
        store,
        schedule=claimed[0],
        error="network error",
        retry_delay_seconds=90,
        failed_at=failed_at,
    )
    assert failed is not None
    assert failed.status == SCHEDULE_STATUS_PENDING
    assert failed.last_error == "network error"
    assert failed.due_at >= failed_at + 89


def test_schedule_state_roundtrip_and_version_conflict(store: SQLiteSessionStore) -> None:
    schedule = create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Track mailbox cursor",
        due_at=time.time() + 30,
    )

    state, version = get_schedule_state(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id=schedule.schedule_id,
    )
    assert state is None
    assert version == 0

    state, version = set_schedule_state(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id=schedule.schedule_id,
        state_json={"cursor": "A1"},
        expected_version=0,
    )
    assert state == {"cursor": "A1"}
    assert version == 1

    with pytest.raises(ScheduleStateConflictError):
        set_schedule_state(
            store,
            session_id="s1",
            thread_id="t1",
            schedule_id=schedule.schedule_id,
            state_json={"cursor": "A2"},
            expected_version=0,
        )


def test_schedule_run_record_lifecycle(store: SQLiteSessionStore) -> None:
    schedule = create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        prompt="Run audit sample",
        due_at=time.time() + 60,
    )
    run_record = create_schedule_run(
        store,
        schedule=schedule,
        trigger_prompt="test trigger",
    )
    assert run_record.status == SCHEDULE_RUN_STATUS_RUNNING
    assert run_record.finished_at is None

    finished = finish_schedule_run(
        store,
        run_id=run_record.run_id,
        status=SCHEDULE_RUN_STATUS_DONE,
        result_text="all good",
        notified_count=2,
    )
    assert finished is not None
    assert finished.status == SCHEDULE_RUN_STATUS_DONE
    assert finished.result_text == "all good"
    assert finished.notified_count == 2
    assert finished.finished_at is not None

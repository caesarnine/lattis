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
    SCHEDULE_TRIGGER_CRON,
    SCHEDULE_TRIGGER_ONCE,
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
    parse_due_at,
    validate_cron,
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


def test_validate_cron_requires_five_fields() -> None:
    assert validate_cron("0 * * * *") == "0 * * * *"
    with pytest.raises(ScheduleValidationError):
        validate_cron("*/5 * * * * *")  # seconds are not supported


def test_create_update_list_cancel_schedule(store: SQLiteSessionStore) -> None:
    due_at = time.time() + 120
    created = create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        name="break",
        prompt="Take a break",
        trigger_type=SCHEDULE_TRIGGER_ONCE,
        run_at=due_at,
    )
    assert created.status == SCHEDULE_STATUS_PENDING

    listed = list_schedules(store, session_id="s1", thread_id="t1")
    assert any(item.name == "heartbeat" for item in listed)
    assert any(item.schedule_id == created.schedule_id for item in listed)

    updated = update_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id=created.schedule_id,
        prompt="Take a longer break",
        enabled=False,
    )
    assert updated.prompt == "Take a longer break"
    assert updated.enabled is False

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
        name="one-shot",
        prompt="One-shot task",
        trigger_type=SCHEDULE_TRIGGER_ONCE,
        run_at=time.time() - 5,
    )
    claimed = claim_due_schedules(store, limit=5, lease_seconds=30)
    assert any(item.name == "one-shot" for item in claimed)
    record = next(item for item in claimed if item.name == "one-shot")
    assert record.status == SCHEDULE_STATUS_RUNNING

    completed = complete_schedule_run(store, schedule=record, completed_at=time.time())
    assert completed is not None
    assert completed.status == SCHEDULE_STATUS_DONE
    assert completed.last_run_at is not None


def test_complete_recurring_schedule_reschedules(store: SQLiteSessionStore) -> None:
    now = 1_700_000_000.0
    schedule = store.create_schedule_record(
        schedule_id="sched-test-cron",
        session_id="s1",
        thread_id="t1",
        name="recurring",
        prompt="Recurring task",
        trigger_type=SCHEDULE_TRIGGER_CRON,
        run_at=None,
        cron="*/1 * * * *",
        timezone="UTC",
        next_run_at=now - 60,
        enabled=True,
        protected=False,
        created_at=now - 120,
    )
    assert schedule.status == SCHEDULE_STATUS_PENDING

    claimed = claim_due_schedules(store, limit=5, lease_seconds=30, now=now)
    record = next(item for item in claimed if item.name == "recurring")
    completed_at = now
    completed = complete_schedule_run(store, schedule=record, completed_at=completed_at)
    assert completed is not None
    assert completed.status == SCHEDULE_STATUS_PENDING
    assert completed.next_run_at > completed_at
    assert completed.next_run_at - completed_at <= 60


def test_fail_schedule_run_retries_with_error(store: SQLiteSessionStore) -> None:
    create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        name="failing",
        prompt="Failing task",
        trigger_type=SCHEDULE_TRIGGER_ONCE,
        run_at=time.time() - 30,
    )
    claimed = claim_due_schedules(store, limit=5, lease_seconds=30)
    record = next(item for item in claimed if item.name == "failing")
    failed_at = time.time()
    failed = fail_schedule_run(
        store,
        schedule=record,
        error="network error",
        retry_delay_seconds=90,
        failed_at=failed_at,
    )
    assert failed is not None
    assert failed.status == SCHEDULE_STATUS_PENDING
    assert failed.last_error == "network error"
    assert failed.next_run_at >= failed_at + 89


def test_schedule_state_roundtrip_and_version_conflict(store: SQLiteSessionStore) -> None:
    schedule = create_schedule(
        store,
        session_id="s1",
        thread_id="t1",
        name="state",
        prompt="Track mailbox cursor",
        trigger_type=SCHEDULE_TRIGGER_ONCE,
        run_at=time.time() + 30,
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
        name="audit",
        prompt="Run audit sample",
        trigger_type=SCHEDULE_TRIGGER_ONCE,
        run_at=time.time() + 60,
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

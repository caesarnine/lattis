from __future__ import annotations

from pathlib import Path

from lattis.domain.outbox import (
    OUTBOX_STATUS_DEAD,
    OUTBOX_STATUS_QUEUED,
    OUTBOX_STATUS_SENT,
    claim_due_notifications,
    enqueue_notification,
    mark_notification_dead,
    mark_notification_sent,
    retry_notification,
)
from lattis.storage.sqlite import SQLiteSessionStore


def _make_store(tmp_path: Path) -> SQLiteSessionStore:
    store = SQLiteSessionStore(tmp_path / "lattis.db")
    store.save_thread("s1", "t1", messages=[])
    return store


def test_enqueue_notification_is_idempotent_by_dedupe_key(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    first = enqueue_notification(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id="sched-1",
        schedule_run_id="run-1",
        channel="telegram",
        external_conversation_id="123",
        text="hello",
        dedupe_key="dedupe-1",
    )
    second = enqueue_notification(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id="sched-1",
        schedule_run_id="run-1",
        channel="telegram",
        external_conversation_id="123",
        text="hello",
        dedupe_key="dedupe-1",
    )
    assert first.outbox_id == second.outbox_id


def test_outbox_claim_retry_and_dead(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    enqueue_notification(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id="sched-1",
        schedule_run_id="run-1",
        channel="telegram",
        external_conversation_id="123",
        text="hello",
        dedupe_key="dedupe-1",
    )

    claimed = claim_due_notifications(store, limit=5, lease_seconds=30)
    assert len(claimed) == 1
    assert claimed[0].attempt_count == 1

    retry = retry_notification(
        store,
        outbox_id=claimed[0].outbox_id,
        error="rate limited",
        retry_delay_seconds=10,
    )
    assert retry is not None
    assert retry.status == OUTBOX_STATUS_QUEUED

    claimed_again = claim_due_notifications(store, limit=5, lease_seconds=30, now=retry.available_at + 1)
    assert len(claimed_again) == 1

    dead = mark_notification_dead(
        store,
        outbox_id=claimed_again[0].outbox_id,
        error="permanent failure",
    )
    assert dead is not None
    assert dead.status == OUTBOX_STATUS_DEAD


def test_outbox_claim_and_mark_sent(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    enqueue_notification(
        store,
        session_id="s1",
        thread_id="t1",
        schedule_id="sched-1",
        schedule_run_id="run-1",
        channel="telegram",
        external_conversation_id="123",
        text="hello",
        dedupe_key="dedupe-1",
    )

    claimed = claim_due_notifications(store, limit=5, lease_seconds=30)
    sent = mark_notification_sent(store, outbox_id=claimed[0].outbox_id)
    assert sent is not None
    assert sent.status == OUTBOX_STATUS_SENT

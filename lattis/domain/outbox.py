from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from lattis.domain.sessions import SessionStore

OUTBOX_STATUS_QUEUED = "queued"
OUTBOX_STATUS_LEASED = "leased"
OUTBOX_STATUS_SENT = "sent"
OUTBOX_STATUS_DEAD = "dead"

OUTBOX_ACTIVE_STATUSES = {OUTBOX_STATUS_QUEUED, OUTBOX_STATUS_LEASED}
OUTBOX_TERMINAL_STATUSES = {OUTBOX_STATUS_SENT, OUTBOX_STATUS_DEAD}


class OutboxValidationError(ValueError):
    pass


@dataclass(frozen=True)
class NotificationOutboxRecord:
    outbox_id: str
    session_id: str
    thread_id: str
    schedule_id: str | None
    schedule_run_id: str | None
    channel: str
    external_conversation_id: str
    payload_json: dict[str, Any]
    dedupe_key: str
    status: str
    attempt_count: int
    available_at: float
    lease_expires_at: float | None
    last_error: str | None
    created_at: float
    updated_at: float

    @property
    def text(self) -> str:
        value = self.payload_json.get("text")
        if isinstance(value, str):
            return value
        return ""


def new_outbox_id() -> str:
    return f"out-{uuid.uuid4().hex[:12]}"


def enqueue_notification(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    schedule_id: str | None,
    schedule_run_id: str | None,
    channel: str,
    external_conversation_id: str,
    text: str,
    dedupe_key: str,
) -> NotificationOutboxRecord:
    normalized_channel = channel.strip().casefold()
    if not normalized_channel:
        raise OutboxValidationError("channel cannot be empty.")
    normalized_conversation = external_conversation_id.strip()
    if not normalized_conversation:
        raise OutboxValidationError("external conversation id cannot be empty.")
    normalized_dedupe = dedupe_key.strip()
    if not normalized_dedupe:
        raise OutboxValidationError("dedupe key cannot be empty.")

    normalized_text = text.strip()
    if not normalized_text:
        raise OutboxValidationError("notification text cannot be empty.")

    now = time.time()
    payload_json: dict[str, Any] = {"text": normalized_text}
    return store.enqueue_notification_outbox_record(
        outbox_id=new_outbox_id(),
        session_id=session_id,
        thread_id=thread_id,
        schedule_id=schedule_id,
        schedule_run_id=schedule_run_id,
        channel=normalized_channel,
        external_conversation_id=normalized_conversation,
        payload_json=payload_json,
        dedupe_key=normalized_dedupe,
        available_at=now,
        created_at=now,
    )


def claim_due_notifications(
    store: SessionStore,
    *,
    limit: int,
    lease_seconds: int,
    now: float | None = None,
) -> list[NotificationOutboxRecord]:
    claimed_at = time.time() if now is None else now
    return store.claim_notification_outbox_records(
        now=claimed_at,
        limit=max(1, min(limit, 100)),
        lease_seconds=max(1, lease_seconds),
    )


def mark_notification_sent(
    store: SessionStore,
    *,
    outbox_id: str,
    sent_at: float | None = None,
) -> NotificationOutboxRecord | None:
    completed_at = time.time() if sent_at is None else sent_at
    return store.mark_notification_outbox_record_sent(
        outbox_id=outbox_id,
        sent_at=completed_at,
    )


def retry_notification(
    store: SessionStore,
    *,
    outbox_id: str,
    error: str,
    retry_delay_seconds: int,
    failed_at: float | None = None,
) -> NotificationOutboxRecord | None:
    now = time.time() if failed_at is None else failed_at
    retry_at = now + max(1, retry_delay_seconds)
    return store.mark_notification_outbox_record_retry(
        outbox_id=outbox_id,
        retry_at=retry_at,
        failed_at=now,
        error=error.strip() or "notification delivery failed",
    )


def mark_notification_dead(
    store: SessionStore,
    *,
    outbox_id: str,
    error: str,
    failed_at: float | None = None,
) -> NotificationOutboxRecord | None:
    now = time.time() if failed_at is None else failed_at
    return store.mark_notification_outbox_record_dead(
        outbox_id=outbox_id,
        failed_at=now,
        error=error.strip() or "notification delivery failed",
    )

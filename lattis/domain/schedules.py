from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from lattis.domain.sessions import SessionStore
from lattis.domain.threads import ThreadNotFoundError

SCHEDULE_STATUS_PENDING = "pending"
SCHEDULE_STATUS_RUNNING = "running"
SCHEDULE_STATUS_DONE = "done"
SCHEDULE_STATUS_CANCELED = "canceled"

ACTIVE_STATUSES = {SCHEDULE_STATUS_PENDING, SCHEDULE_STATUS_RUNNING}
TERMINAL_STATUSES = {SCHEDULE_STATUS_DONE, SCHEDULE_STATUS_CANCELED}


class ScheduleValidationError(ValueError):
    pass


class ScheduleNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class ScheduleRecord:
    schedule_id: str
    session_id: str
    thread_id: str
    prompt: str
    due_at: float
    interval_seconds: int | None
    status: str
    lease_expires_at: float | None
    attempt_count: int
    last_error: str | None
    last_run_at: float | None
    created_at: float
    updated_at: float

    @property
    def is_recurring(self) -> bool:
        return self.interval_seconds is not None


def new_schedule_id() -> str:
    return f"sched-{uuid.uuid4().hex[:12]}"


def parse_due_at(value: str) -> float:
    text = value.strip()
    if not text:
        raise ScheduleValidationError("due_at cannot be empty.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleValidationError(
            "due_at must be an ISO-8601 datetime, for example 2026-02-20T09:00:00-05:00."
        ) from exc
    if parsed.tzinfo is None:
        raise ScheduleValidationError(
            "due_at must include a timezone offset (e.g. 'Z' or '-05:00')."
        )
    return parsed.astimezone(timezone.utc).timestamp()


def format_due_at(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def next_due_for_interval(*, current_due_at: float, interval_seconds: int, now: float) -> float:
    if interval_seconds <= 0:
        raise ScheduleValidationError("interval_seconds must be greater than zero.")
    next_due = current_due_at + interval_seconds
    if next_due > now:
        return next_due
    missed = int((now - current_due_at) // interval_seconds) + 1
    return current_due_at + (interval_seconds * missed)


def create_schedule(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    prompt: str,
    due_at: float,
    interval_seconds: int | None = None,
) -> ScheduleRecord:
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise ScheduleValidationError("prompt cannot be empty.")
    if due_at <= 0:
        raise ScheduleValidationError("due_at must be a valid UTC timestamp.")
    if interval_seconds is not None and interval_seconds <= 0:
        raise ScheduleValidationError("interval_seconds must be greater than zero.")
    if not store.thread_exists(session_id, thread_id):
        raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
    created_at = time.time()
    return store.create_schedule_record(
        schedule_id=new_schedule_id(),
        session_id=session_id,
        thread_id=thread_id,
        prompt=cleaned_prompt,
        due_at=due_at,
        interval_seconds=interval_seconds,
        created_at=created_at,
    )


def list_schedules(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    include_terminal: bool = False,
    limit: int = 20,
) -> list[ScheduleRecord]:
    bounded_limit = max(1, min(limit, 100))
    return store.list_schedule_records(
        session_id=session_id,
        thread_id=thread_id,
        include_terminal=include_terminal,
        limit=bounded_limit,
    )


def get_schedule(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    schedule_id: str,
) -> ScheduleRecord:
    record = store.get_schedule_record(schedule_id)
    if not record or record.session_id != session_id or record.thread_id != thread_id:
        raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")
    return record


def update_schedule(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    schedule_id: str,
    prompt: str | None = None,
    due_at: float | None = None,
    interval_seconds: int | None = None,
    clear_recurrence: bool = False,
) -> ScheduleRecord:
    current = get_schedule(store, session_id=session_id, thread_id=thread_id, schedule_id=schedule_id)
    if current.status in TERMINAL_STATUSES:
        raise ScheduleValidationError("Cannot edit a completed or canceled schedule.")

    next_prompt = current.prompt if prompt is None else prompt.strip()
    if not next_prompt:
        raise ScheduleValidationError("prompt cannot be empty.")

    next_due_at = current.due_at if due_at is None else due_at
    if next_due_at <= 0:
        raise ScheduleValidationError("due_at must be a valid UTC timestamp.")

    if clear_recurrence:
        next_interval = None
    elif interval_seconds is None:
        next_interval = current.interval_seconds
    else:
        if interval_seconds <= 0:
            raise ScheduleValidationError("interval_seconds must be greater than zero.")
        next_interval = interval_seconds

    updated = store.update_schedule_record(
        schedule_id=schedule_id,
        session_id=session_id,
        thread_id=thread_id,
        prompt=next_prompt,
        due_at=next_due_at,
        interval_seconds=next_interval,
        updated_at=time.time(),
    )
    if updated is None:
        raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")
    return updated


def cancel_schedule(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    schedule_id: str,
) -> ScheduleRecord:
    canceled = store.cancel_schedule_record(
        schedule_id=schedule_id,
        session_id=session_id,
        thread_id=thread_id,
        canceled_at=time.time(),
    )
    if canceled is None:
        raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")
    return canceled


def claim_due_schedules(
    store: SessionStore,
    *,
    limit: int,
    lease_seconds: int,
    now: float | None = None,
) -> list[ScheduleRecord]:
    claimed_at = time.time() if now is None else now
    return store.claim_due_schedule_records(
        now=claimed_at,
        limit=max(1, min(limit, 100)),
        lease_seconds=max(1, lease_seconds),
    )


def complete_schedule_run(
    store: SessionStore,
    *,
    schedule: ScheduleRecord,
    completed_at: float | None = None,
) -> ScheduleRecord | None:
    now = time.time() if completed_at is None else completed_at
    next_due_at: float | None = None
    if schedule.interval_seconds is not None:
        next_due_at = next_due_for_interval(
            current_due_at=schedule.due_at,
            interval_seconds=schedule.interval_seconds,
            now=now,
        )
    return store.complete_claimed_schedule_record(
        schedule_id=schedule.schedule_id,
        completed_at=now,
        next_due_at=next_due_at,
    )


def fail_schedule_run(
    store: SessionStore,
    *,
    schedule: ScheduleRecord,
    error: str,
    retry_delay_seconds: int,
    failed_at: float | None = None,
) -> ScheduleRecord | None:
    now = time.time() if failed_at is None else failed_at
    retry_at = now + max(1, retry_delay_seconds)
    return store.fail_claimed_schedule_record(
        schedule_id=schedule.schedule_id,
        failed_at=now,
        retry_at=retry_at,
        error=error.strip() or "unknown schedule error",
    )


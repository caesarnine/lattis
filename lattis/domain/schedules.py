from __future__ import annotations

import time
import uuid
from typing import Any
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from lattis.domain.sessions import SessionStore
from lattis.domain.threads import ThreadNotFoundError

SCHEDULE_STATUS_PENDING = "pending"
SCHEDULE_STATUS_RUNNING = "running"
SCHEDULE_STATUS_DONE = "done"
SCHEDULE_STATUS_CANCELED = "canceled"

ACTIVE_STATUSES = {SCHEDULE_STATUS_PENDING, SCHEDULE_STATUS_RUNNING}
TERMINAL_STATUSES = {SCHEDULE_STATUS_DONE, SCHEDULE_STATUS_CANCELED}

SCHEDULE_TRIGGER_ONCE = "once"
SCHEDULE_TRIGGER_CRON = "cron"

SCHEDULE_RUN_STATUS_RUNNING = "running"
SCHEDULE_RUN_STATUS_DONE = "done"
SCHEDULE_RUN_STATUS_FAILED = "failed"


class ScheduleValidationError(ValueError):
    pass


class ScheduleNotFoundError(LookupError):
    pass


class ScheduleStateConflictError(ValueError):
    pass


@dataclass(frozen=True)
class ScheduleRecord:
    schedule_id: str
    session_id: str
    thread_id: str
    name: str
    prompt: str
    trigger_type: str
    run_at: float | None
    cron: str | None
    timezone: str | None
    next_run_at: float
    enabled: bool
    protected: bool
    status: str
    lease_expires_at: float | None
    attempt_count: int
    last_error: str | None
    last_run_at: float | None
    state_json: dict[str, Any] | None
    state_version: int
    created_at: float
    updated_at: float

    @property
    def is_recurring(self) -> bool:
        return self.trigger_type == SCHEDULE_TRIGGER_CRON

    @property
    def is_one_shot(self) -> bool:
        return self.trigger_type == SCHEDULE_TRIGGER_ONCE


@dataclass(frozen=True)
class ScheduleRunRecord:
    run_id: str
    schedule_id: str
    session_id: str
    thread_id: str
    status: str
    trigger_prompt: str
    result_text: str | None
    error: str | None
    notified_count: int
    started_at: float
    finished_at: float | None
    created_at: float
    updated_at: float


def new_schedule_id() -> str:
    return f"sched-{uuid.uuid4().hex[:12]}"


def new_schedule_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def parse_due_at(value: str) -> float:
    return parse_run_at(value)


def parse_run_at(value: str) -> float:
    text = value.strip()
    if not text:
        raise ScheduleValidationError("run_at cannot be empty.")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ScheduleValidationError(
            "run_at must be an ISO-8601 datetime, for example 2026-02-20T09:00:00-05:00."
        ) from exc
    if parsed.tzinfo is None:
        raise ScheduleValidationError(
            "run_at must include a timezone offset (e.g. 'Z' or '-05:00')."
        )
    return parsed.astimezone(timezone.utc).timestamp()


def format_due_at(value: float) -> str:
    return format_timestamp(value)


def format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timezone(value: str | None) -> timezone | ZoneInfo:
    if value is None:
        return timezone.utc
    text = value.strip()
    if not text or text.upper() in {"UTC", "Z"}:
        return timezone.utc
    if text.startswith(("+", "-")) and len(text) in {6, 3}:
        try:
            sign = 1 if text[0] == "+" else -1
            if len(text) == 3:
                hours = sign * int(text[1:3])
                minutes = 0
            else:
                hours = sign * int(text[1:3])
                minutes = sign * int(text[4:6])
            delta = timedelta(hours=hours, minutes=minutes)
            return timezone(delta)
        except Exception as exc:
            raise ScheduleValidationError(f"Invalid timezone offset: {value!r}") from exc
    try:
        return ZoneInfo(text)
    except Exception as exc:
        raise ScheduleValidationError(
            f"Unknown timezone: {value!r}. Use an IANA name like 'America/New_York' or an offset like '-05:00'."
        ) from exc


def validate_cron(value: str) -> str:
    text = " ".join(value.strip().split())
    if not text:
        raise ScheduleValidationError("cron cannot be empty.")
    if text.startswith("@"):
        raise ScheduleValidationError("cron macros are not supported; use standard 5-field cron.")
    parts = text.split(" ")
    if len(parts) != 5:
        raise ScheduleValidationError(
            "cron must have exactly 5 fields: 'minute hour day month weekday' (no seconds)."
        )
    try:
        from croniter import croniter  # type: ignore[import-not-found]

        croniter(text, datetime.now(timezone.utc))
    except ScheduleValidationError:
        raise
    except Exception as exc:
        raise ScheduleValidationError(f"Invalid cron expression: {text!r}.") from exc
    return text


def next_run_for_cron(*, cron: str, timezone_name: str | None, after: float) -> float:
    from croniter import croniter  # type: ignore[import-not-found]

    tz = _parse_timezone(timezone_name)
    base = datetime.fromtimestamp(after, tz=timezone.utc).astimezone(tz)
    iterator = croniter(cron, base)
    next_local: datetime = iterator.get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=tz)
    return next_local.astimezone(timezone.utc).timestamp()


def preview_cron_runs(
    *,
    cron: str,
    timezone_name: str | None,
    start_after: float,
    count: int = 3,
) -> list[float]:
    from croniter import croniter  # type: ignore[import-not-found]

    tz = _parse_timezone(timezone_name)
    base = datetime.fromtimestamp(start_after, tz=timezone.utc).astimezone(tz)
    iterator = croniter(cron, base)
    runs: list[float] = []
    for _ in range(max(1, min(count, 10))):
        next_local: datetime = iterator.get_next(datetime)
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=tz)
        runs.append(next_local.astimezone(timezone.utc).timestamp())
    return runs


def create_schedule(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    name: str,
    prompt: str,
    trigger_type: str,
    run_at: float | None = None,
    cron: str | None = None,
    timezone: str | None = None,
    enabled: bool = True,
    protected: bool = False,
) -> ScheduleRecord:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise ScheduleValidationError("name cannot be empty.")
    cleaned_prompt = prompt.strip()
    if not cleaned_prompt:
        raise ScheduleValidationError("prompt cannot be empty.")
    if trigger_type not in {SCHEDULE_TRIGGER_ONCE, SCHEDULE_TRIGGER_CRON}:
        raise ScheduleValidationError("trigger_type must be 'once' or 'cron'.")
    next_run_at: float
    validated_cron: str | None = None
    if trigger_type == SCHEDULE_TRIGGER_ONCE:
        if run_at is None or run_at <= 0:
            raise ScheduleValidationError("run_at must be a valid UTC timestamp.")
        next_run_at = run_at
        cron = None
        timezone = None
    else:
        if cron is None:
            raise ScheduleValidationError("cron is required for cron schedules.")
        validated_cron = validate_cron(cron)
        next_run_at = next_run_for_cron(
            cron=validated_cron,
            timezone_name=timezone,
            after=time.time(),
        )
        run_at = None
    if not store.thread_exists(session_id, thread_id):
        raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
    created_at = time.time()
    return store.create_schedule_record(
        schedule_id=new_schedule_id(),
        session_id=session_id,
        thread_id=thread_id,
        name=cleaned_name,
        prompt=cleaned_prompt,
        trigger_type=trigger_type,
        run_at=run_at,
        cron=validated_cron,
        timezone=timezone.strip() if isinstance(timezone, str) and timezone.strip() else None,
        next_run_at=next_run_at,
        enabled=enabled,
        protected=protected,
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
    name: str | None = None,
    prompt: str | None = None,
    trigger_type: str | None = None,
    run_at: float | None = None,
    cron: str | None = None,
    timezone: str | None = None,
    enabled: bool | None = None,
) -> ScheduleRecord:
    current = get_schedule(store, session_id=session_id, thread_id=thread_id, schedule_id=schedule_id)
    if current.status in TERMINAL_STATUSES:
        raise ScheduleValidationError("Cannot edit a completed or canceled schedule.")

    next_name = current.name if name is None else name.strip()
    if not next_name:
        raise ScheduleValidationError("name cannot be empty.")

    next_prompt = current.prompt if prompt is None else prompt.strip()
    if not next_prompt:
        raise ScheduleValidationError("prompt cannot be empty.")

    next_enabled = current.enabled if enabled is None else bool(enabled)

    resolved_type = current.trigger_type if trigger_type is None else trigger_type.strip()
    if resolved_type not in {SCHEDULE_TRIGGER_ONCE, SCHEDULE_TRIGGER_CRON}:
        raise ScheduleValidationError("trigger_type must be 'once' or 'cron'.")

    next_run_at = current.next_run_at
    next_run_at_value: float | None = current.run_at
    next_cron = current.cron
    next_timezone = current.timezone
    trigger_changed = False

    if resolved_type == SCHEDULE_TRIGGER_ONCE:
        if current.trigger_type != SCHEDULE_TRIGGER_ONCE:
            if run_at is None:
                raise ScheduleValidationError("run_at is required when switching to a one-shot schedule.")
            trigger_changed = True

        if run_at is not None:
            if run_at <= 0:
                raise ScheduleValidationError("run_at must be a valid UTC timestamp.")
            next_run_at_value = run_at
            next_run_at = run_at
            trigger_changed = True

        next_cron = None
        next_timezone = None
    else:
        if current.trigger_type != SCHEDULE_TRIGGER_CRON:
            if cron is None:
                raise ScheduleValidationError("cron is required when switching to a cron schedule.")
            trigger_changed = True

        if cron is not None:
            next_cron = validate_cron(cron)
            trigger_changed = True
        if timezone is not None:
            next_timezone = timezone.strip() or None
            trigger_changed = True

        if not next_cron:
            raise ScheduleValidationError("cron is required for cron schedules.")

        next_run_at_value = None
        if trigger_changed:
            next_run_at = next_run_for_cron(
                cron=next_cron,
                timezone_name=next_timezone,
                after=time.time(),
            )

    updated = store.update_schedule_record(
        schedule_id=schedule_id,
        session_id=session_id,
        thread_id=thread_id,
        name=next_name,
        prompt=next_prompt,
        trigger_type=resolved_type,
        run_at=next_run_at_value,
        cron=next_cron,
        timezone=next_timezone,
        next_run_at=next_run_at,
        enabled=next_enabled,
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


def delete_schedule(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    schedule_id: str,
) -> bool:
    record = get_schedule(store, session_id=session_id, thread_id=thread_id, schedule_id=schedule_id)
    if record.protected:
        raise ScheduleValidationError("Cannot delete a protected schedule.")
    return store.delete_schedule_record(schedule_id=schedule_id, session_id=session_id, thread_id=thread_id)


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
    if schedule.trigger_type == SCHEDULE_TRIGGER_CRON and schedule.cron is not None:
        next_due_at = next_run_for_cron(
            cron=schedule.cron,
            timezone_name=schedule.timezone,
            after=now,
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


def get_schedule_state(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    schedule_id: str,
) -> tuple[dict[str, Any] | None, int]:
    record = get_schedule(
        store,
        session_id=session_id,
        thread_id=thread_id,
        schedule_id=schedule_id,
    )
    return record.state_json, record.state_version


def set_schedule_state(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
    schedule_id: str,
    state_json: dict[str, Any] | None,
    expected_version: int | None = None,
) -> tuple[dict[str, Any] | None, int]:
    updated = store.set_schedule_state_record(
        schedule_id=schedule_id,
        session_id=session_id,
        thread_id=thread_id,
        state_json=state_json,
        expected_version=expected_version,
        updated_at=time.time(),
    )
    if updated is None:
        existing = store.get_schedule_record(schedule_id)
        if existing is None or existing.session_id != session_id or existing.thread_id != thread_id:
            raise ScheduleNotFoundError(f"Schedule '{schedule_id}' not found.")
        raise ScheduleStateConflictError(
            f"Schedule state version mismatch for '{schedule_id}'."
        )
    return updated.state_json, updated.state_version


def create_schedule_run(
    store: SessionStore,
    *,
    schedule: ScheduleRecord,
    trigger_prompt: str,
    started_at: float | None = None,
) -> ScheduleRunRecord:
    now = time.time() if started_at is None else started_at
    return store.create_schedule_run_record(
        run_id=new_schedule_run_id(),
        schedule_id=schedule.schedule_id,
        session_id=schedule.session_id,
        thread_id=schedule.thread_id,
        trigger_prompt=trigger_prompt,
        started_at=now,
    )


def finish_schedule_run(
    store: SessionStore,
    *,
    run_id: str,
    status: str,
    result_text: str | None = None,
    error: str | None = None,
    notified_count: int = 0,
    finished_at: float | None = None,
) -> ScheduleRunRecord | None:
    now = time.time() if finished_at is None else finished_at
    return store.finish_schedule_run_record(
        run_id=run_id,
        status=status,
        result_text=result_text,
        error=error,
        notified_count=max(0, notified_count),
        finished_at=now,
    )

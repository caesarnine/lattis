from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent, RunContext

from lattis.agents.plugin import AgentRunContext
from lattis.domain.schedules import (
    ScheduleRecord,
    ScheduleStateConflictError,
    cancel_schedule,
    create_schedule,
    format_due_at,
    get_schedule_state,
    list_schedules,
    parse_due_at,
    set_schedule_state,
    update_schedule,
)
from lattis.domain.sessions import SessionStore


@dataclass
class SchedulerToolRuntime:
    schedule_id: str
    notifications: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScheduleToolDeps:
    store: SessionStore
    session_id: str
    thread_id: str
    scheduler_trigger: bool = False
    runtime: SchedulerToolRuntime | None = None


def create_schedule_tool_deps(ctx: AgentRunContext) -> ScheduleToolDeps:
    scheduler_trigger = bool(getattr(ctx.run_input, "scheduler_trigger", False))
    raw_schedule_id = getattr(ctx.run_input, "schedule_id", None)
    schedule_id = raw_schedule_id if isinstance(raw_schedule_id, str) and raw_schedule_id else None
    runtime = SchedulerToolRuntime(schedule_id=schedule_id) if scheduler_trigger and schedule_id else None
    return ScheduleToolDeps(
        store=ctx.store,
        session_id=ctx.session_id,
        thread_id=ctx.thread_id,
        scheduler_trigger=scheduler_trigger,
        runtime=runtime,
    )


def collect_scheduler_notifications(deps: object) -> list[str]:
    if not isinstance(deps, ScheduleToolDeps):
        return []
    if deps.runtime is None:
        return []
    return [item for item in deps.runtime.notifications if item.strip()]


def register_schedule_tools(agent: Agent[ScheduleToolDeps, Any]) -> None:
    @agent.tool
    def current_time(
        _ctx: RunContext[ScheduleToolDeps],
    ) -> dict[str, str | int]:
        """
        Return the server's current time.

        Use this when the user says relative times like "in 2 minutes", "tomorrow",
        or "at 9am" and you need an accurate reference point.
        """
        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now().astimezone()
        return {
            "now_utc": now_utc.isoformat().replace("+00:00", "Z"),
            "now_local": now_local.isoformat(),
            "local_timezone": now_local.tzname() or "local",
            "unix_seconds": int(now_utc.timestamp()),
        }

    @agent.tool
    def schedule_create(
        ctx: RunContext[ScheduleToolDeps],
        prompt: str,
        due_at: str | None = None,
        delay_seconds: int | None = None,
        interval_seconds: int | None = None,
    ) -> str:
        """
        Create a reminder schedule.

        - Set exactly one of `due_at` or `delay_seconds`.
        - Use `delay_seconds` for relative requests (for example "in 120 seconds").
        - `due_at` must be an ISO-8601 datetime with timezone offset.
        - Set `interval_seconds` to make the schedule recurring.
        """
        if ctx.deps.scheduler_trigger:
            return _SCHEDULER_DISABLED_MESSAGE
        due_at_ts = _resolve_due_at(
            due_at=due_at,
            delay_seconds=delay_seconds,
        )
        record = create_schedule(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            prompt=prompt,
            due_at=due_at_ts,
            interval_seconds=interval_seconds,
        )
        return _render_schedule_created(record)

    @agent.tool
    def schedule_list(
        ctx: RunContext[ScheduleToolDeps],
        include_terminal: bool = False,
        limit: int = 20,
    ) -> str:
        """
        List schedules for the current thread.
        """
        if ctx.deps.scheduler_trigger:
            return _SCHEDULER_DISABLED_MESSAGE
        records = list_schedules(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            include_terminal=include_terminal,
            limit=limit,
        )
        if not records:
            return "No schedules found."
        lines = ["Schedules:"]
        for item in records:
            lines.append(_render_schedule_line(item))
        return "\n".join(lines)

    @agent.tool
    def schedule_update(
        ctx: RunContext[ScheduleToolDeps],
        schedule_id: str,
        prompt: str | None = None,
        due_at: str | None = None,
        delay_seconds: int | None = None,
        interval_seconds: int | None = None,
        clear_recurrence: bool = False,
    ) -> str:
        """
        Edit an existing schedule.

        - Provide `due_at` (absolute) or `delay_seconds` (relative), but not both.
        - `due_at` must be ISO-8601 with timezone offset when provided.
        - Use `clear_recurrence=true` to convert to one-shot.
        """
        if ctx.deps.scheduler_trigger:
            return _SCHEDULER_DISABLED_MESSAGE
        due_at_ts = _resolve_optional_due_at(
            due_at=due_at,
            delay_seconds=delay_seconds,
        )
        record = update_schedule(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            schedule_id=schedule_id,
            prompt=prompt,
            due_at=due_at_ts,
            interval_seconds=interval_seconds,
            clear_recurrence=clear_recurrence,
        )
        return f"Updated {record.schedule_id}: {_render_schedule_line(record)}"

    @agent.tool
    def schedule_cancel(
        ctx: RunContext[ScheduleToolDeps],
        schedule_id: str,
    ) -> str:
        """
        Cancel an active schedule.
        """
        if ctx.deps.scheduler_trigger:
            return _SCHEDULER_DISABLED_MESSAGE
        record = cancel_schedule(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            schedule_id=schedule_id,
        )
        return f"Canceled {record.schedule_id}."

    @agent.tool
    def schedule_state_get(
        ctx: RunContext[ScheduleToolDeps],
    ) -> dict[str, Any]:
        """
        Read state for the currently executing schedule trigger.
        """
        runtime = _scheduler_runtime(ctx.deps)
        if runtime is None:
            return {"error": _SCHEDULER_ONLY_MESSAGE}
        state, version = get_schedule_state(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            schedule_id=runtime.schedule_id,
        )
        return {
            "schedule_id": runtime.schedule_id,
            "version": version,
            "state": state,
        }

    @agent.tool
    def schedule_state_set(
        ctx: RunContext[ScheduleToolDeps],
        state: dict[str, Any] | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """
        Write state for the currently executing schedule trigger.
        """
        runtime = _scheduler_runtime(ctx.deps)
        if runtime is None:
            return {"error": _SCHEDULER_ONLY_MESSAGE}
        try:
            updated_state, version = set_schedule_state(
                ctx.deps.store,
                session_id=ctx.deps.session_id,
                thread_id=ctx.deps.thread_id,
                schedule_id=runtime.schedule_id,
                state_json=state,
                expected_version=expected_version,
            )
        except ScheduleStateConflictError as exc:
            return {"schedule_id": runtime.schedule_id, "error": str(exc)}
        return {
            "schedule_id": runtime.schedule_id,
            "version": version,
            "state": updated_state,
        }

    @agent.tool
    def notify_user(
        ctx: RunContext[ScheduleToolDeps],
        message: str,
    ) -> str:
        """
        Queue a proactive user notification for this schedule run.
        """
        runtime = _scheduler_runtime(ctx.deps)
        if runtime is None:
            return _SCHEDULER_ONLY_MESSAGE
        text = message.strip()
        if not text:
            return "Ignored empty notification."
        runtime.notifications.append(text)
        return f"Queued notification ({len(runtime.notifications)})."


_SCHEDULER_DISABLED_MESSAGE = (
    "Schedule CRUD tools are unavailable during scheduler-triggered runs."
)
_SCHEDULER_ONLY_MESSAGE = (
    "This tool is only available during scheduler-triggered runs."
)


def _scheduler_runtime(deps: ScheduleToolDeps) -> SchedulerToolRuntime | None:
    if not deps.scheduler_trigger:
        return None
    return deps.runtime


def _resolve_due_at(*, due_at: str | None, delay_seconds: int | None) -> float:
    if due_at and delay_seconds is not None:
        raise ValueError("Use either due_at or delay_seconds, not both.")
    if due_at:
        return parse_due_at(due_at)
    if delay_seconds is None:
        raise ValueError("Either due_at or delay_seconds is required.")
    if delay_seconds <= 0:
        raise ValueError("delay_seconds must be greater than zero.")
    return time.time() + float(delay_seconds)


def _resolve_optional_due_at(*, due_at: str | None, delay_seconds: int | None) -> float | None:
    if due_at is None and delay_seconds is None:
        return None
    return _resolve_due_at(due_at=due_at, delay_seconds=delay_seconds)


def _render_schedule_created(record: ScheduleRecord) -> str:
    recurrence = (
        f"every {record.interval_seconds} seconds"
        if record.interval_seconds is not None
        else "one-shot"
    )
    return (
        f"Created {record.schedule_id} for {format_due_at(record.due_at)} "
        f"({recurrence})."
    )


def _render_schedule_line(record: ScheduleRecord) -> str:
    recurrence = (
        f"repeat={record.interval_seconds}s"
        if record.interval_seconds is not None
        else "repeat=none"
    )
    return (
        f"{record.schedule_id} status={record.status} "
        f"due={format_due_at(record.due_at)} {recurrence} "
        f"prompt={record.prompt!r}"
    )

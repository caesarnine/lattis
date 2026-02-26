from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Annotated, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from lattis.agents.plugin import AgentRunContext
from lattis.domain.schedules import (
    ACTIVE_STATUSES,
    SCHEDULE_STATUS_RUNNING,
    SCHEDULE_TRIGGER_CRON,
    SCHEDULE_TRIGGER_ONCE,
    ScheduleRecord,
    ScheduleStateConflictError,
    ScheduleValidationError,
    delete_schedule,
    format_timestamp,
    get_schedule_state,
    list_schedules,
    new_schedule_id,
    next_run_for_cron,
    parse_run_at,
    preview_cron_runs,
    set_schedule_state,
    update_schedule,
    validate_cron,
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
    runtime = getattr(deps, "runtime", None)
    notifications = getattr(runtime, "notifications", None)
    if not isinstance(notifications, list):
        return []
    return [item for item in notifications if isinstance(item, str) and item.strip()]


class OnceTriggerInput(BaseModel):
    type: Literal["once"] = Field(default="once", description="Run exactly once.")
    run_at: str | None = Field(
        default=None,
        description="ISO-8601 datetime with timezone offset, e.g. '2026-02-26T09:00:00-05:00'.",
    )
    delay_seconds: int | None = Field(
        default=None,
        description="Run this many seconds from now (alternative to run_at).",
    )


class CronTriggerInput(BaseModel):
    type: Literal["cron"] = Field(default="cron", description="Run periodically using standard 5-field cron (no seconds).")
    cron: str = Field(description="Cron expression: 'minute hour day month weekday' (5 fields).")
    timezone: str = Field(
        default="UTC",
        description="IANA timezone (e.g. 'America/New_York') or fixed offset (e.g. '-05:00'). Defaults to UTC.",
    )


ScheduleTriggerInput = Annotated[OnceTriggerInput | CronTriggerInput, Field(discriminator="type")]


def register_schedule_tools(agent: Agent[Any, Any]) -> None:
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
    def schedule_upsert(
        ctx: RunContext[ScheduleToolDeps],
        prompt: str,
        trigger: ScheduleTriggerInput,
        name: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """
        Create or update a schedule in the current thread.

        Args:
            prompt: The task request to run at each trigger.
            trigger: Trigger definition (one-shot or cron).
            name: Stable schedule name. If omitted, a name is generated.
            enabled: If false, the schedule will not run until re-enabled.
        """
        if ctx.deps.scheduler_trigger:
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_DISABLED_MESSAGE}}

        cleaned_prompt = prompt.strip()
        if not cleaned_prompt:
            return {"ok": False, "error": {"code": "validation_error", "message": "prompt cannot be empty."}}

        schedule_name = _normalize_schedule_name(name)
        is_heartbeat = schedule_name == "heartbeat"

        now = time.time()
        existing = ctx.deps.store.get_schedule_record_by_name(
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            name=schedule_name,
        )
        if _is_actively_running(existing, now=now):
            return {
                "ok": False,
                "error": {
                    "code": "schedule_running",
                    "message": f"Schedule '{schedule_name}' is currently running; try again later.",
                },
                "schedule": _schedule_to_dict(existing),
            }

        try:
            payload = _resolve_trigger(trigger, now=now)
        except (ScheduleValidationError, ValueError) as exc:
            return {"ok": False, "error": {"code": "validation_error", "message": str(exc)}}

        record = ctx.deps.store.upsert_schedule_record(
            schedule_id=new_schedule_id(),
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            name=schedule_name,
            prompt=cleaned_prompt,
            trigger_type=payload["trigger_type"],
            run_at=payload["run_at"],
            cron=payload["cron"],
            timezone=payload["timezone"],
            next_run_at=payload["next_run_at"],
            enabled=bool(enabled),
            protected=bool(is_heartbeat),
            now=now,
        )

        return {
            "ok": True,
            "schedule": _schedule_to_dict(record),
            "preview": payload["preview"],
        }

    @agent.tool
    def schedule_get(
        ctx: RunContext[ScheduleToolDeps],
        name_or_id: str,
    ) -> dict[str, Any]:
        """
        Get a schedule by name or ID.
        """
        if ctx.deps.scheduler_trigger:
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_DISABLED_MESSAGE}}
        record = _get_schedule_by_name_or_id(ctx, name_or_id=name_or_id)
        if record is None:
            return {"ok": False, "error": {"code": "not_found", "message": "Schedule not found."}}
        return {"ok": True, "schedule": _schedule_to_dict(record), "preview": _preview_for_record(record)}

    @agent.tool
    def schedule_list(
        ctx: RunContext[ScheduleToolDeps],
        include_terminal: bool = False,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        List schedules for the current thread.
        """
        if ctx.deps.scheduler_trigger:
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_DISABLED_MESSAGE}}
        records = list_schedules(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            include_terminal=include_terminal,
            limit=limit,
        )
        return {"ok": True, "schedules": [_schedule_to_dict(item) for item in records]}

    @agent.tool
    def schedule_set_enabled(
        ctx: RunContext[ScheduleToolDeps],
        name_or_id: str,
        enabled: bool,
    ) -> dict[str, Any]:
        """
        Enable or disable a schedule by name or ID.
        """
        if ctx.deps.scheduler_trigger:
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_DISABLED_MESSAGE}}
        record = _get_schedule_by_name_or_id(ctx, name_or_id=name_or_id)
        if record is None:
            return {"ok": False, "error": {"code": "not_found", "message": "Schedule not found."}}
        if record.status not in ACTIVE_STATUSES:
            return {
                "ok": False,
                "error": {"code": "not_editable", "message": "Only active schedules can be enabled/disabled."},
                "schedule": _schedule_to_dict(record),
            }
        if _is_actively_running(record, now=time.time()):
            return {
                "ok": False,
                "error": {"code": "schedule_running", "message": "Schedule is currently running; try again later."},
                "schedule": _schedule_to_dict(record),
            }
        updated = update_schedule(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            schedule_id=record.schedule_id,
            enabled=bool(enabled),
        )
        return {"ok": True, "schedule": _schedule_to_dict(updated), "preview": _preview_for_record(updated)}

    @agent.tool
    def schedule_delete(
        ctx: RunContext[ScheduleToolDeps],
        name_or_id: str,
    ) -> dict[str, Any]:
        """
        Permanently delete a schedule by name or ID.

        Note: the default 'heartbeat' schedule is protected and cannot be deleted.
        """
        if ctx.deps.scheduler_trigger:
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_DISABLED_MESSAGE}}
        record = _get_schedule_by_name_or_id(ctx, name_or_id=name_or_id)
        if record is None:
            return {"ok": False, "error": {"code": "not_found", "message": "Schedule not found."}}
        if record.protected:
            return {
                "ok": False,
                "error": {"code": "protected_schedule", "message": "This schedule cannot be deleted."},
                "schedule": _schedule_to_dict(record),
            }
        if _is_actively_running(record, now=time.time()):
            return {
                "ok": False,
                "error": {"code": "schedule_running", "message": "Schedule is currently running; try again later."},
                "schedule": _schedule_to_dict(record),
            }
        try:
            deleted = delete_schedule(
                ctx.deps.store,
                session_id=ctx.deps.session_id,
                thread_id=ctx.deps.thread_id,
                schedule_id=record.schedule_id,
            )
        except ScheduleValidationError as exc:
            return {"ok": False, "error": {"code": "validation_error", "message": str(exc)}}
        return {"ok": True, "deleted": deleted, "schedule_id": record.schedule_id}

    @agent.tool
    def schedule_state_get(
        ctx: RunContext[ScheduleToolDeps],
    ) -> dict[str, Any]:
        """
        Read state for the currently executing schedule trigger.
        """
        runtime = _scheduler_runtime(ctx.deps)
        if runtime is None:
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_ONLY_MESSAGE}}
        state, version = get_schedule_state(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            schedule_id=runtime.schedule_id,
        )
        return {"ok": True, "schedule_id": runtime.schedule_id, "version": version, "state": state}

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
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_ONLY_MESSAGE}}
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
            return {"ok": False, "schedule_id": runtime.schedule_id, "error": str(exc)}
        return {"ok": True, "schedule_id": runtime.schedule_id, "version": version, "state": updated_state}

    @agent.tool
    def notify_user(
        ctx: RunContext[ScheduleToolDeps],
        message: str,
    ) -> dict[str, Any]:
        """
        Queue a proactive user notification for this schedule run.
        """
        runtime = _scheduler_runtime(ctx.deps)
        if runtime is None:
            return {"ok": False, "error": {"code": "forbidden", "message": _SCHEDULER_ONLY_MESSAGE}}
        text = message.strip()
        if not text:
            return {"ok": True, "queued": 0}
        runtime.notifications.append(text)
        return {"ok": True, "queued": len(runtime.notifications)}


_SCHEDULER_DISABLED_MESSAGE = "Schedule management tools are unavailable during scheduler-triggered runs."
_SCHEDULER_ONLY_MESSAGE = "This tool is only available during scheduler-triggered runs."


def _scheduler_runtime(deps: object) -> SchedulerToolRuntime | None:
    if not bool(getattr(deps, "scheduler_trigger", False)):
        return None
    runtime = getattr(deps, "runtime", None)
    return runtime if isinstance(runtime, SchedulerToolRuntime) else None


def _normalize_schedule_name(value: str | None) -> str:
    if value is None or not value.strip():
        return f"task-{uuid.uuid4().hex[:8]}"
    return value.strip()


def _is_actively_running(record: ScheduleRecord | None, *, now: float) -> bool:
    if record is None:
        return False
    if record.status != SCHEDULE_STATUS_RUNNING:
        return False
    if record.lease_expires_at is None:
        return True
    return record.lease_expires_at > now


def _resolve_trigger(trigger: ScheduleTriggerInput, *, now: float) -> dict[str, Any]:
    if trigger.type == "once":
        if trigger.run_at and trigger.delay_seconds is not None:
            raise ValueError("For one-shot schedules, provide either run_at or delay_seconds, not both.")
        if trigger.run_at:
            run_at_ts = parse_run_at(trigger.run_at)
        elif trigger.delay_seconds is not None:
            if trigger.delay_seconds <= 0:
                raise ValueError("delay_seconds must be greater than zero.")
            run_at_ts = now + float(trigger.delay_seconds)
        else:
            raise ValueError("For one-shot schedules, either run_at or delay_seconds is required.")
        return {
            "trigger_type": SCHEDULE_TRIGGER_ONCE,
            "run_at": run_at_ts,
            "cron": None,
            "timezone": None,
            "next_run_at": run_at_ts,
            "preview": {
                "next_runs_utc": [format_timestamp(run_at_ts)],
            },
        }

    cron_expr = validate_cron(trigger.cron)
    tz_name = (trigger.timezone or "UTC").strip() or "UTC"
    next_run_at = next_run_for_cron(cron=cron_expr, timezone_name=tz_name, after=now)
    preview = [format_timestamp(ts) for ts in preview_cron_runs(cron=cron_expr, timezone_name=tz_name, start_after=now)]
    return {
        "trigger_type": SCHEDULE_TRIGGER_CRON,
        "run_at": None,
        "cron": cron_expr,
        "timezone": tz_name,
        "next_run_at": next_run_at,
        "preview": {
            "next_runs_utc": preview,
        },
    }


def _get_schedule_by_name_or_id(ctx: RunContext[ScheduleToolDeps], *, name_or_id: str) -> ScheduleRecord | None:
    text = (name_or_id or "").strip()
    if not text:
        return None
    if text.startswith("sched-"):
        record = ctx.deps.store.get_schedule_record(text)
        if record and record.session_id == ctx.deps.session_id and record.thread_id == ctx.deps.thread_id:
            return record
        return None
    return ctx.deps.store.get_schedule_record_by_name(
        session_id=ctx.deps.session_id,
        thread_id=ctx.deps.thread_id,
        name=text,
    )


def _preview_for_record(record: ScheduleRecord) -> dict[str, Any]:
    if record.trigger_type == SCHEDULE_TRIGGER_ONCE:
        runs: list[str] = []
        if record.run_at is not None:
            runs = [format_timestamp(record.run_at)]
        return {"next_runs_utc": runs}

    if not record.cron:
        return {"next_runs_utc": []}
    now = time.time()
    runs = preview_cron_runs(cron=record.cron, timezone_name=record.timezone, start_after=now)
    return {"next_runs_utc": [format_timestamp(ts) for ts in runs]}


def _schedule_to_dict(record: ScheduleRecord) -> dict[str, Any]:
    trigger: dict[str, Any]
    if record.trigger_type == SCHEDULE_TRIGGER_ONCE:
        trigger = {
            "type": "once",
            "run_at_utc": format_timestamp(record.run_at) if record.run_at is not None else None,
        }
    else:
        trigger = {
            "type": "cron",
            "cron": record.cron,
            "timezone": record.timezone or "UTC",
        }
    return {
        "id": record.schedule_id,
        "name": record.name,
        "prompt": record.prompt,
        "trigger": trigger,
        "enabled": record.enabled,
        "protected": record.protected,
        "status": record.status,
        "next_run_at_utc": format_timestamp(record.next_run_at),
        "last_run_at_utc": format_timestamp(record.last_run_at) if record.last_run_at is not None else None,
        "last_error": record.last_error,
        "attempt_count": record.attempt_count,
        "created_at_utc": format_timestamp(record.created_at),
        "updated_at_utc": format_timestamp(record.updated_at),
    }

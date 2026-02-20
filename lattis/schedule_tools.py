from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext

from lattis.agents.plugin import AgentRunContext
from lattis.domain.schedules import (
    ScheduleRecord,
    cancel_schedule,
    create_schedule,
    format_due_at,
    list_schedules,
    parse_due_at,
    update_schedule,
)
from lattis.domain.sessions import SessionStore


@dataclass(frozen=True)
class ScheduleToolDeps:
    store: SessionStore
    session_id: str
    thread_id: str
    enabled: bool = True


def create_schedule_tool_deps(ctx: AgentRunContext) -> ScheduleToolDeps:
    enabled = not bool(getattr(ctx.run_input, "scheduler_trigger", False))
    return ScheduleToolDeps(
        store=ctx.store,
        session_id=ctx.session_id,
        thread_id=ctx.thread_id,
        enabled=enabled,
    )


def register_schedule_tools(agent: Agent[ScheduleToolDeps, Any]) -> None:
    @agent.tool
    def schedule_create(
        ctx: RunContext[ScheduleToolDeps],
        prompt: str,
        due_at: str,
        interval_seconds: int | None = None,
    ) -> str:
        """
        Create a reminder schedule.

        - `due_at` must be an ISO-8601 datetime with timezone offset.
        - Set `interval_seconds` to make the schedule recurring.
        """
        if not ctx.deps.enabled:
            return "Scheduling tools are disabled for scheduler-triggered runs."
        due_at_ts = parse_due_at(due_at)
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
        if not ctx.deps.enabled:
            return "Scheduling tools are disabled for scheduler-triggered runs."
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
        interval_seconds: int | None = None,
        clear_recurrence: bool = False,
    ) -> str:
        """
        Edit an existing schedule.

        - `due_at` must be ISO-8601 with timezone offset when provided.
        - Use `clear_recurrence=true` to convert to one-shot.
        """
        if not ctx.deps.enabled:
            return "Scheduling tools are disabled for scheduler-triggered runs."
        due_at_ts = parse_due_at(due_at) if due_at is not None else None
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
        if not ctx.deps.enabled:
            return "Scheduling tools are disabled for scheduler-triggered runs."
        record = cancel_schedule(
            ctx.deps.store,
            session_id=ctx.deps.session_id,
            thread_id=ctx.deps.thread_id,
            schedule_id=schedule_id,
        )
        return f"Canceled {record.schedule_id}."


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

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Sequence

from pydantic import BaseModel, ConfigDict

from pydantic_ai.messages import ModelMessage

if TYPE_CHECKING:
    from lattis.domain.schedules import ScheduleRecord, ScheduleRunRecord


@dataclass
class ThreadState:
    session_id: str
    thread_id: str
    messages: list[ModelMessage]


class ThreadSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent: str | None = None


class SessionStore(Protocol):
    def load_thread(
        self,
        session_id: str,
        thread_id: str,
    ) -> ThreadState | None: ...

    def save_thread(
        self,
        session_id: str,
        thread_id: str,
        *,
        messages: Sequence[ModelMessage],
    ) -> None: ...

    def list_threads(self, session_id: str) -> list[str]: ...

    def thread_exists(self, session_id: str, thread_id: str) -> bool: ...

    def list_sessions(self) -> list[str]: ...

    def delete_thread(self, session_id: str, thread_id: str) -> None: ...

    def get_session_model(self, session_id: str) -> str | None: ...

    def set_session_model(self, session_id: str, model: str | None) -> None: ...

    def get_thread_settings(self, session_id: str, thread_id: str) -> ThreadSettings: ...

    def set_thread_settings(self, session_id: str, thread_id: str, settings: ThreadSettings) -> None: ...

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------
    def create_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        prompt: str,
        due_at: float,
        interval_seconds: int | None,
        created_at: float,
    ) -> "ScheduleRecord": ...

    def get_schedule_record(self, schedule_id: str) -> "ScheduleRecord | None": ...

    def list_schedule_records(
        self,
        *,
        session_id: str,
        thread_id: str,
        include_terminal: bool,
        limit: int,
    ) -> list["ScheduleRecord"]: ...

    def update_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        prompt: str,
        due_at: float,
        interval_seconds: int | None,
        updated_at: float,
    ) -> "ScheduleRecord | None": ...

    def cancel_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        canceled_at: float,
    ) -> "ScheduleRecord | None": ...

    def claim_due_schedule_records(
        self,
        *,
        now: float,
        limit: int,
        lease_seconds: int,
    ) -> list["ScheduleRecord"]: ...

    def complete_claimed_schedule_record(
        self,
        *,
        schedule_id: str,
        completed_at: float,
        next_due_at: float | None,
    ) -> "ScheduleRecord | None": ...

    def fail_claimed_schedule_record(
        self,
        *,
        schedule_id: str,
        failed_at: float,
        retry_at: float,
        error: str,
    ) -> "ScheduleRecord | None": ...

    def set_schedule_state_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        state_json: dict[str, object] | None,
        expected_version: int | None,
        updated_at: float,
    ) -> "ScheduleRecord | None": ...

    def create_schedule_run_record(
        self,
        *,
        run_id: str,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        trigger_prompt: str,
        started_at: float,
    ) -> "ScheduleRunRecord": ...

    def finish_schedule_run_record(
        self,
        *,
        run_id: str,
        status: str,
        result_text: str | None,
        error: str | None,
        notified_count: int,
        finished_at: float,
    ) -> "ScheduleRunRecord | None": ...


def generate_thread_id(prefix: str = "thread") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

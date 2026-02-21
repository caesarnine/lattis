"""Domain logic and shared abstractions."""

from lattis.domain.sessions import SessionStore, ThreadSettings, ThreadState, generate_thread_id
from lattis.domain.schedules import (
    ScheduleNotFoundError,
    ScheduleRecord,
    ScheduleRunRecord,
    ScheduleStateConflictError,
    ScheduleValidationError,
)
from lattis.domain.threads import ThreadAlreadyExistsError, ThreadNotFoundError

__all__ = [
    "SessionStore",
    "ThreadSettings",
    "ThreadState",
    "ScheduleRecord",
    "ScheduleRunRecord",
    "ScheduleValidationError",
    "ScheduleNotFoundError",
    "ScheduleStateConflictError",
    "ThreadAlreadyExistsError",
    "ThreadNotFoundError",
    "generate_thread_id",
]

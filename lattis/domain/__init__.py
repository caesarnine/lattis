"""Domain logic and shared abstractions."""

from lattis.domain.sessions import SessionStore, ThreadSettings, ThreadState, generate_thread_id
from lattis.domain.channels import (
    ChannelBindingConflictError,
    ChannelBindingRecord,
    ChannelBindingValidationError,
)
from lattis.domain.outbox import NotificationOutboxRecord
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
    "ChannelBindingRecord",
    "ChannelBindingValidationError",
    "ChannelBindingConflictError",
    "NotificationOutboxRecord",
    "ScheduleRecord",
    "ScheduleRunRecord",
    "ScheduleValidationError",
    "ScheduleNotFoundError",
    "ScheduleStateConflictError",
    "ThreadAlreadyExistsError",
    "ThreadNotFoundError",
    "generate_thread_id",
]

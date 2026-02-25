from __future__ import annotations

import time

import pytest

from lattis.domain.schedules import (
    SCHEDULE_TRIGGER_CRON,
    SCHEDULE_TRIGGER_ONCE,
    ScheduleValidationError,
)
from lattis.schedule_tools import CronTriggerInput, OnceTriggerInput, _resolve_trigger


def test_resolve_once_from_delay_seconds() -> None:
    now = time.time()
    payload = _resolve_trigger(OnceTriggerInput(delay_seconds=120), now=now)
    assert payload["trigger_type"] == SCHEDULE_TRIGGER_ONCE
    assert now + 119 <= payload["next_run_at"] <= now + 121


def test_resolve_once_from_absolute_string() -> None:
    payload = _resolve_trigger(OnceTriggerInput(run_at="2026-03-01T09:00:00Z"), now=time.time())
    assert payload["trigger_type"] == SCHEDULE_TRIGGER_ONCE
    assert payload["run_at"] > 0


def test_resolve_once_requires_input() -> None:
    with pytest.raises(ValueError, match="either run_at or delay_seconds is required"):
        _resolve_trigger(OnceTriggerInput(), now=time.time())


def test_resolve_once_rejects_both_absolute_and_delay() -> None:
    with pytest.raises(ValueError, match="either run_at or delay_seconds"):
        _resolve_trigger(OnceTriggerInput(run_at="2026-03-01T09:00:00Z", delay_seconds=30), now=time.time())


def test_resolve_cron_includes_preview_runs() -> None:
    payload = _resolve_trigger(CronTriggerInput(cron="0 * * * *", timezone="UTC"), now=time.time())
    assert payload["trigger_type"] == SCHEDULE_TRIGGER_CRON
    assert payload["cron"] == "0 * * * *"
    assert payload["timezone"] == "UTC"
    preview = payload["preview"]["next_runs_utc"]
    assert isinstance(preview, list)
    assert len(preview) == 3


def test_resolve_cron_rejects_six_field() -> None:
    with pytest.raises(ScheduleValidationError):
        _resolve_trigger(CronTriggerInput(cron="*/5 * * * * *", timezone="UTC"), now=time.time())


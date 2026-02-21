from __future__ import annotations

import time

import pytest

from lattis.schedule_tools import _resolve_due_at, _resolve_optional_due_at, _resolve_schedule_create_due_at


def test_resolve_due_at_from_delay_seconds() -> None:
    before = time.time()
    due_at = _resolve_due_at(due_at=None, delay_seconds=120)
    after = time.time()
    assert before + 119 <= due_at <= after + 121


def test_resolve_due_at_from_absolute_string() -> None:
    due_at = _resolve_due_at(due_at="2026-03-01T09:00:00Z", delay_seconds=None)
    assert due_at > 0


def test_resolve_due_at_requires_input() -> None:
    with pytest.raises(ValueError, match="Either due_at or delay_seconds is required"):
        _resolve_due_at(due_at=None, delay_seconds=None)


def test_resolve_due_at_rejects_both_absolute_and_delay() -> None:
    with pytest.raises(ValueError, match="either due_at or delay_seconds"):
        _resolve_due_at(due_at="2026-03-01T09:00:00Z", delay_seconds=30)


def test_resolve_optional_due_at_none() -> None:
    assert _resolve_optional_due_at(due_at=None, delay_seconds=None) is None


def test_resolve_schedule_create_due_at_defaults_to_interval() -> None:
    before = time.time()
    due_at = _resolve_schedule_create_due_at(
        due_at=None,
        delay_seconds=None,
        interval_seconds=120,
    )
    after = time.time()
    assert before + 119 <= due_at <= after + 121

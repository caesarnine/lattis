from __future__ import annotations

import pytest

from lattis.cli import _resolve_up_telegram_enabled


def test_resolve_up_telegram_enabled_auto_without_token() -> None:
    assert _resolve_up_telegram_enabled(mode="auto", token="") is False


def test_resolve_up_telegram_enabled_auto_with_token() -> None:
    assert _resolve_up_telegram_enabled(mode="auto", token="abc123") is True


def test_resolve_up_telegram_enabled_on_requires_token() -> None:
    with pytest.raises(ValueError, match="no token was provided"):
        _resolve_up_telegram_enabled(mode="on", token="")


def test_resolve_up_telegram_enabled_on_with_token() -> None:
    assert _resolve_up_telegram_enabled(mode="on", token="abc123") is True


def test_resolve_up_telegram_enabled_off() -> None:
    assert _resolve_up_telegram_enabled(mode="off", token="abc123") is False


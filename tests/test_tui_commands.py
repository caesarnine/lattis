from __future__ import annotations

import asyncio

from lattice.tui.commands import CommandSuggester, parse_command


def _run(coro):
    return asyncio.run(coro)


def test_parse_command_aliases() -> None:
    command = parse_command("/?")
    assert command is not None
    assert command.name == "help"
    assert command.args == []
    assert command.raw == "/?"

    command = parse_command("/exit now")
    assert command is not None
    assert command.name == "quit"
    assert command.args == ["now"]


def test_parse_command_non_command() -> None:
    assert parse_command("") is None
    assert parse_command("hello") is None
    assert parse_command("/") is None


def test_agent_reset_suggestion() -> None:
    suggester = CommandSuggester()
    assert _run(suggester.get_suggestion("/agent r")) == "/agent reset"
    assert _run(suggester.get_suggestion("/agent res")) == "/agent reset"


def test_model_reset_suggestion() -> None:
    suggester = CommandSuggester()
    assert _run(suggester.get_suggestion("/model re")) == "/model reset"

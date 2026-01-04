from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from textual.suggester import Suggester


@dataclass(frozen=True)
class CommandSpec:
    usage: str
    description: str
    completions: tuple[str, ...] = ()


COMMAND_SPECS: tuple[CommandSpec, ...] = (
    CommandSpec("/help", "Show this help message", completions=("/help", "/?")),
    CommandSpec("/threads", "List threads", completions=("/threads",)),
    CommandSpec("/thread <id>", "Switch to a thread", completions=("/thread",)),
    CommandSpec(
        "/thread new [id]",
        "Create a new thread",
        completions=("/thread new", "/thread create"),
    ),
    CommandSpec(
        "/thread delete <id>",
        "Delete a thread",
        completions=("/thread delete", "/thread del", "/thread rm"),
    ),
    CommandSpec("/clear", "Clear current thread history", completions=("/clear",)),
    CommandSpec("/agent", "Show current agent", completions=("/agent",)),
    CommandSpec(
        "/agent list [filter]",
        "List or search agents",
        completions=("/agent list",),
    ),
    CommandSpec(
        "/agent set <id|number>",
        "Set thread agent",
        completions=("/agent set",),
    ),
    CommandSpec(
        "/agent default",
        "Reset to default agent",
        completions=("/agent default", "/agent reset"),
    ),
    CommandSpec("/model", "Show current model", completions=("/model",)),
    CommandSpec(
        "/model list [filter]",
        "List or search models",
        completions=("/model list",),
    ),
    CommandSpec(
        "/model set <name>",
        "Set session model",
        completions=("/model set",),
    ),
    CommandSpec(
        "/model default",
        "Reset to default model",
        completions=("/model default", "/model reset"),
    ),
    CommandSpec("/quit or /exit", "Exit the app", completions=("/quit", "/exit")),
)


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    args: list[str]
    raw: str


_COMMAND_ALIASES = {"?": "help", "exit": "quit"}


def command_completions() -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for spec in COMMAND_SPECS:
        items = spec.completions or (spec.usage.split()[0],)
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
    return ordered


def build_help_text() -> str:
    width = max(len(spec.usage) for spec in COMMAND_SPECS)
    lines = ["Commands:"]
    for spec in COMMAND_SPECS:
        lines.append(f"{spec.usage.ljust(width + 2)}{spec.description}")
    return "\n".join(lines)


def parse_command(value: str) -> ParsedCommand | None:
    if not value or not value.startswith("/"):
        return None
    parts = value.strip().split()
    if not parts:
        return None
    name = parts[0].lstrip("/").lower()
    if not name:
        return None
    name = _COMMAND_ALIASES.get(name, name)
    return ParsedCommand(name=name, args=parts[1:], raw=value)


class CommandSuggester(Suggester):
    def __init__(
        self,
        *,
        commands: Sequence[str] | None = None,
        model_provider: Callable[[], Sequence[str]] | None = None,
        agent_provider: Callable[[], Sequence[str]] | None = None,
    ) -> None:
        super().__init__(use_cache=False, case_sensitive=False)
        self._commands = list(commands) if commands is not None else command_completions()
        self._model_provider = model_provider or (lambda: [])
        self._agent_provider = agent_provider or (lambda: [])

    async def get_suggestion(self, value: str) -> str | None:
        if not value.startswith("/"):
            return None

        if value.startswith("/model"):
            return self._suggest_from_choices(value, root="model", choices=self._model_provider())

        if value.startswith("/agent"):
            return self._suggest_from_choices(value, root="agent", choices=self._agent_provider())

        for command in self._commands:
            if command.startswith(value):
                return command
        return None

    def _suggest_from_choices(
        self, value: str, *, root: str, choices: Sequence[str]
    ) -> str | None:
        root_cmd = f"/{root}"
        if value == root_cmd:
            return f"{root_cmd} "

        remainder = value[len(root_cmd) :].lstrip()
        if remainder and "list".startswith(remainder):
            return f"{root_cmd} list "
        if remainder and "default".startswith(remainder):
            return f"{root_cmd} default"
        if remainder and "reset".startswith(remainder):
            return f"{root_cmd} reset"
        if remainder and "set".startswith(remainder):
            return f"{root_cmd} set "
        if remainder.startswith("list"):
            return f"{root_cmd} list "
        if remainder.startswith("default"):
            return f"{root_cmd} default"
        if remainder.startswith("reset"):
            return f"{root_cmd} reset"
        if remainder.startswith("set"):
            if remainder == "set":
                return f"{root_cmd} set "
            if remainder.startswith("set "):
                prefix = remainder[4:]
                base = f"{root_cmd} set "
            else:
                prefix = remainder
                base = f"{root_cmd} "
        else:
            prefix = remainder
            base = f"{root_cmd} "

        if not choices:
            return None

        needle = prefix.casefold()
        for choice in choices:
            if choice.casefold().startswith(needle):
                return f"{base}{choice}"
        return None

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional
from uuid import uuid4

if TYPE_CHECKING:
    from lattice.cli import ConnectionInfo

from pydantic_ai.ui.vercel_ai.request_types import (
    DynamicToolInputAvailablePart,
    DynamicToolOutputAvailablePart,
    DynamicToolOutputErrorPart,
    FileUIPart,
    ReasoningUIPart,
    SubmitMessage,
    TextUIPart,
    ToolInputAvailablePart,
    ToolOutputAvailablePart,
    ToolOutputErrorPart,
    UIMessage,
)
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Static

from lattice.client import AgentClient
from lattice.core.session import generate_thread_id
from lattice.tui.commands import CommandSuggester, ParsedCommand, build_help_text, parse_command
from lattice.tui.widgets import ChatMessage, ToolCall


class AgentApp(App):
    """Terminal client for an agent server."""

    CSS = """
    Screen {
        background: #0d1117;
    }

    #header {
        height: 2;
        dock: top;
        background: #161b22;
        border-bottom: solid #30363d;
        padding: 0 1;
    }

    #header-left {
        width: 1fr;
        content-align: left middle;
        color: #e6edf3;
        text-style: bold;
    }

    #header-right {
        width: auto;
        content-align: right middle;
        color: #7d8590;
    }

    #chat-scroll {
        height: 1fr;
        padding: 1 2;
        background: #0d1117;
    }

    #input-container {
        height: 3;
        dock: bottom;
        background: #161b22;
        border-top: solid #30363d;
        padding: 0 1;
    }

    #input {
        width: 1fr;
        border: none;
        background: #0d1117;
        color: #e6edf3;
        padding: 0 1;
    }

    #input:focus {
        border: none;
    }

    #status {
        width: 12;
        content-align: right middle;
        color: #7d8590;
    }

    #status.streaming {
        color: #58a6ff;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "cancel_run", "Cancel", show=False),
        Binding("ctrl+l", "clear_chat", "Clear", show=False),
    ]

    def __init__(
        self,
        *,
        client: AgentClient,
        connection_info: ConnectionInfo | None = None,
    ):
        super().__init__()
        self.session_id = "..."
        self.thread_id = "..."  # Placeholder until mounted
        self.agent_id: str | None = None
        self.agent_name: str | None = None
        self._default_agent: str | None = None
        self._agent_cache: list[tuple[str, str]] | None = None
        self._agent_loading = False
        self.model_name: str | None = None
        self._default_model: str | None = None
        self._model_cache: list[str] | None = None
        self._model_loading = False
        self.client = client
        self.connection_info = connection_info
        self._command_suggester = CommandSuggester(
            model_provider=self._get_model_suggestions,
            agent_provider=self._get_agent_suggestions,
        )

        self._worker = None
        self._current_assistant: Optional[ChatMessage] = None
        self._current_thinking: Optional[ChatMessage] = None
        self._tool_calls: dict[str, ToolCall] = {}
        self._message_map: dict[str, ChatMessage] = {}
        self._mounted = False
        self._event_handlers = {
            "text-start": self._on_text_start_event,
            "text-delta": self._on_text_delta_event,
            "reasoning-start": self._on_reasoning_start_event,
            "reasoning-delta": self._on_reasoning_delta_event,
            "tool-input-start": self._on_tool_input_start_event,
            "tool-input-delta": self._on_tool_input_delta_event,
            "tool-input-available": self._on_tool_input_available_event,
            "tool-output-available": self._on_tool_output_available_event,
            "tool-output-error": self._on_tool_output_error_event,
            "error": self._on_error_event,
        }

    def compose(self) -> ComposeResult:
        with Horizontal(id="header"):
            yield Static("Agent", id="header-left")
            yield Static(self.thread_id, id="header-right")
        yield VerticalScroll(id="chat-scroll")
        with Horizontal(id="input-container"):
            yield Input(
                placeholder="Ask something... (/help)",
                id="input",
                suggester=self._command_suggester,
            )
            yield Static("", id="status")

    async def on_mount(self) -> None:
        self._mounted = True
        self.query_one("#input", Input).focus()

        try:
            self.session_id = await self.client.get_session_id()
        except Exception as exc:
            self._add_system_message(f"Failed to load session: {exc}")
            return

        threads = await self.client.list_threads(self.session_id)
        if threads:
            self.thread_id = threads[0]
        else:
            self.thread_id = "default"
            await self.client.create_thread(self.session_id, self.thread_id)

        await self._refresh_agent()
        await self._refresh_model()
        self.run_worker(self._load_thread_state(self.thread_id), exclusive=False)

    async def on_shutdown(self) -> None:
        await self.client.close()

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_cancel_run(self) -> None:
        if self._worker and self._worker.is_running:
            self._worker.cancel()
            self._set_status("")

    def action_clear_chat(self) -> None:
        chat = self.query_one("#chat-scroll", VerticalScroll)
        chat.remove_children()
        self._reset_message_state()

    # -------------------------------------------------------------------------
    # Input Handling
    # -------------------------------------------------------------------------

    @on(Input.Submitted, "#input")
    async def handle_input(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        event.input.value = ""

        if not user_input:
            return

        command = parse_command(user_input)
        if command and await self._dispatch_command(command):
            return

        self._add_user_message(user_input)
        self._worker = self.run_worker(self._run_agent(user_input), exclusive=True)

    @on(Input.Changed, "#input")
    async def handle_input_changed(self, event: Input.Changed) -> None:
        value = event.value.strip()
        if value.startswith("/model") and self._model_cache is None and not self._model_loading:
            self.run_worker(self._prefetch_models(), exclusive=False)
        if value.startswith("/agent") and self._agent_cache is None and not self._agent_loading:
            self.run_worker(self._prefetch_agents(), exclusive=False)

    async def _dispatch_command(self, command: ParsedCommand) -> bool:
        if command.name == "quit":
            self.exit()
            return True
        if command.name == "clear":
            await self._clear_current_thread()
            return True
        if command.name == "help":
            self._add_system_message(build_help_text())
            return True
        if command.name == "threads":
            threads = await self.client.list_threads(self.session_id)
            listing = ", ".join(threads) if threads else "(none)"
            self._add_system_message(f"Threads: {listing}")
            return True
        if command.name == "thread":
            await self._handle_thread_command(command)
            return True
        if command.name == "agent":
            await self._handle_agent_command(command)
            return True
        if command.name == "model":
            await self._handle_model_command(command)
            return True
        return False

    async def _handle_thread_command(self, command: ParsedCommand) -> None:
        parts = command.args

        if not parts:
            self._add_system_message(f"Current thread: {self.thread_id}")
            return

        subcommand = parts[0].lower()

        if subcommand in {"new", "create"}:
            new_id = parts[1].strip() if len(parts) > 1 else generate_thread_id()
            if await self._thread_exists(new_id):
                self._add_system_message(f"Thread '{new_id}' already exists.")
                return
            await self.client.create_thread(self.session_id, new_id)
            await self._switch_thread(new_id, created=True)
            return

        if subcommand in {"delete", "del", "rm"}:
            if len(parts) < 2:
                self._add_system_message("Usage: /thread delete <id>")
                return
            await self._delete_thread(parts[1].strip())
            return

        target = parts[0].strip()
        if target == self.thread_id:
            self._add_system_message(f"Already on thread '{self.thread_id}'.")
            return
        await self._switch_thread(target, created=not await self._thread_exists(target))

    async def _handle_agent_command(self, command: ParsedCommand) -> None:
        parts = command.args
        if not parts or parts[0].lower() in {"current", "show"}:
            await self._refresh_agent()
            if self.agent_name and self.agent_id:
                self._add_system_message(f"Current agent: {self.agent_name} ({self.agent_id})")
            else:
                self._add_system_message(f"Current agent: {self.agent_id or '(unknown)'}")
            return

        subcommand = parts[0].lower()

        if subcommand == "list":
            query = " ".join(parts[1:]).strip()
            agents = await self._load_agents()
            needle = query.lower()
            if query:
                matches = [
                    (agent_id, name)
                    for agent_id, name in agents
                    if needle in agent_id.lower() or needle in name.lower()
                ]
            else:
                matches = agents

            if not matches:
                self._add_system_message(f"No agents found for '{query}'.")
                return

            limit = 30
            shown = matches[:limit]
            header = f"Agents ({len(matches)} match{'es' if len(matches) != 1 else ''}):"
            lines = [header]
            for i, (agent_id, name) in enumerate(shown, start=1):
                label = f"{name} — {agent_id}" if name and name != agent_id else agent_id
                lines.append(f"{i}. {label}")
            if len(matches) > limit:
                lines.append(f"... showing first {limit}. Use /agent list <filter> to narrow.")
            self._add_system_message("\n".join(lines))
            return

        if subcommand in {"default", "reset"}:
            await self._set_thread_agent(None)
            return

        if subcommand == "set":
            if len(parts) < 2:
                self._add_system_message("Usage: /agent set <agent-id|number>")
                return
            value = " ".join(parts[1:]).strip()
            agent_id = await self._resolve_agent_id(value)
            if agent_id is None:
                return
            await self._set_thread_agent(agent_id)
            return

        # Assume /agent <id|number>
        value = " ".join(parts).strip()
        if not value:
            self._add_system_message("Usage: /agent <agent-id|number>")
            return
        agent_id = await self._resolve_agent_id(value)
        if agent_id is None:
            return
        await self._set_thread_agent(agent_id)

    async def _handle_model_command(self, command: ParsedCommand) -> None:
        parts = command.args
        if not parts or parts[0].lower() in {"current", "show"}:
            await self._refresh_model()
            current = self.model_name or "(unknown)"
            self._add_system_message(f"Current model: {current}")
            return

        subcommand = parts[0].lower()

        if subcommand == "list":
            query = " ".join(parts[1:]).strip()
            models = await self._load_models()
            if query:
                matches = [m for m in models if query.lower() in m.lower()]
            else:
                matches = models

            if not matches:
                self._add_system_message(f"No models found for '{query}'.")
                return

            limit = 30
            shown = matches[:limit]
            header = f"Models ({len(matches)} match{'es' if len(matches) != 1 else ''}):"
            lines = [header, *[f"- {model}" for model in shown]]
            if len(matches) > limit:
                lines.append(f"... showing first {limit}. Use /model list <filter> to narrow.")
            self._add_system_message("\n".join(lines))
            return

        if subcommand in {"default", "reset"}:
            await self._set_session_model(None)
            return

        if subcommand == "set":
            if len(parts) < 2:
                self._add_system_message("Usage: /model set <model-name>")
                return
            model_name = " ".join(parts[1:]).strip()
            await self._set_session_model(model_name)
            return

        # Assume /model <name>
        model_name = " ".join(parts).strip()
        if not model_name:
            self._add_system_message("Usage: /model <model-name>")
            return
        await self._set_session_model(model_name)

    async def _load_models(self) -> list[str]:
        if self._model_cache is not None:
            return self._model_cache
        if self._model_loading:
            return self._model_cache or []
        self._model_loading = True
        try:
            payload = await self.client.list_models()
        except Exception as exc:
            self._add_system_message(f"Failed to load models: {exc}")
            self._model_loading = False
            return []
        self._model_cache = payload.models
        self._default_model = payload.default_model
        self._model_loading = False
        return self._model_cache

    async def _prefetch_models(self) -> None:
        await self._load_models()

    def _get_model_suggestions(self) -> list[str]:
        return self._model_cache or []

    async def _load_agents(self) -> list[tuple[str, str]]:
        if self._agent_cache is not None:
            return self._agent_cache
        if self._agent_loading:
            return self._agent_cache or []
        self._agent_loading = True
        try:
            payload = await self.client.list_agents()
        except Exception as exc:
            self._add_system_message(f"Failed to load agents: {exc}")
            self._agent_loading = False
            return []
        self._agent_cache = [(agent.id, agent.name) for agent in payload.agents]
        self._default_agent = payload.default_agent
        self._agent_loading = False
        return self._agent_cache

    async def _prefetch_agents(self) -> None:
        await self._load_agents()

    def _get_agent_suggestions(self) -> list[str]:
        if not self._agent_cache:
            return []
        return [agent_id for agent_id, _ in self._agent_cache]

    async def _refresh_agent(self) -> None:
        try:
            payload = await self.client.get_thread_agent(self.session_id, self.thread_id)
        except Exception as exc:
            self._add_system_message(f"Failed to load agent: {exc}")
            return
        self.agent_id = payload.agent
        self.agent_name = payload.agent_name
        self._default_agent = payload.default_agent
        self._update_header()

    async def _resolve_agent_id(self, value: str) -> str | None:
        value = value.strip()
        if not value:
            self._add_system_message("Usage: /agent set <agent-id|number>")
            return None

        if value.isdigit():
            idx = int(value)
            if idx <= 0:
                self._add_system_message("Agent number must be >= 1.")
                return None
            agents = await self._load_agents()
            if idx > len(agents):
                self._add_system_message(f"Agent number out of range (1-{len(agents)}).")
                return None
            return agents[idx - 1][0]

        return value

    async def _set_thread_agent(self, agent_id: str | None) -> None:
        try:
            payload = await self.client.set_thread_agent(self.session_id, self.thread_id, agent_id)
        except Exception as exc:
            self._add_system_message(f"Failed to set agent: {exc}")
            return

        self.agent_id = payload.agent
        self.agent_name = payload.agent_name
        self._default_agent = payload.default_agent
        await self._refresh_model()

        label = self.agent_name or self.agent_id or "(unknown)"
        if payload.is_default:
            self._add_system_message(f"Agent reset to default: {label}")
        else:
            self._add_system_message(f"Agent set to: {label}")

    async def _refresh_model(self) -> None:
        try:
            payload = await self.client.get_session_model(self.session_id)
        except Exception as exc:
            self._add_system_message(f"Failed to load model: {exc}")
            return
        self.model_name = payload.model
        self._default_model = payload.default_model
        self._update_header()

    async def _set_session_model(self, model_name: str | None) -> None:
        try:
            payload = await self.client.set_session_model(self.session_id, model_name)
        except Exception as exc:
            self._add_system_message(f"Failed to set model: {exc}")
            return
        self.model_name = payload.model
        self._default_model = payload.default_model
        self._update_header()
        if payload.is_default:
            self._add_system_message(f"Model reset to default: {payload.model}")
        else:
            self._add_system_message(f"Model set to: {payload.model}")

    async def _clear_current_thread(self) -> None:
        self.action_clear_chat()
        try:
            await self.client.clear_thread(self.session_id, self.thread_id)
        except Exception as exc:  # pragma: no cover - UI fallback
            self._add_system_message(f"Failed to clear thread: {exc}")

    # -------------------------------------------------------------------------
    # Agent Streaming
    # -------------------------------------------------------------------------

    async def _run_agent(self, user_input: str) -> None:
        self._set_status("streaming", streaming=True)
        self._reset_message_state()

        run_input = self._build_run_input(user_input)

        try:
            async for event in self.client.run_stream(run_input):
                self._handle_ui_event(event)
        except Exception as exc:
            self._add_system_message(f"Run error: {exc}")
        finally:
            self._set_status("")
            self._scroll_to_bottom()

    def _build_run_input(self, user_input: str) -> SubmitMessage:
        return SubmitMessage(
            id=uuid4().hex,
            messages=[
                UIMessage(
                    id=uuid4().hex,
                    role="user",
                    parts=[TextUIPart(text=user_input)],
                )
            ],
            session_id=self.session_id,
            thread_id=self.thread_id,
        )

    def _handle_ui_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if not isinstance(event_type, str):
            return
        handler = self._event_handlers.get(event_type)
        if handler:
            handler(event)

    def _on_text_start_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("id") or uuid4().hex)
        self._handle_text_message_start(message_id)

    def _on_text_delta_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("id") or "")
        delta = str(event.get("delta") or "")
        if message_id:
            self._handle_text_message_content(message_id, delta)

    def _on_reasoning_start_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("id") or uuid4().hex)
        self._handle_thinking_start(message_id)

    def _on_reasoning_delta_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("id") or "")
        delta = str(event.get("delta") or "")
        if message_id:
            self._handle_thinking_delta(message_id, delta)

    def _on_tool_input_start_event(self, event: dict[str, Any]) -> None:
        self._handle_tool_input_event(event, include_args=False)

    def _on_tool_input_delta_event(self, event: dict[str, Any]) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        delta = str(event.get("inputTextDelta") or "")
        if tool_call_id and delta:
            self._append_tool_args(tool_call_id, delta)

    def _on_tool_input_available_event(self, event: dict[str, Any]) -> None:
        self._handle_tool_input_event(event, include_args=True)

    def _handle_tool_input_event(self, event: dict[str, Any], *, include_args: bool) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        if not tool_call_id:
            return
        tool_name = str(event.get("toolName") or "tool")
        args = event.get("input") if include_args else ""
        self._add_tool_call(tool_name, args, tool_call_id)

    def _on_tool_output_available_event(self, event: dict[str, Any]) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        if tool_call_id:
            self._set_tool_result(tool_call_id, event.get("output"))

    def _on_tool_output_error_event(self, event: dict[str, Any]) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        error_text = str(event.get("errorText") or "Tool error")
        if tool_call_id:
            self._set_tool_result(tool_call_id, {"stderr": error_text, "exit_code": 1})

    def _on_error_event(self, event: dict[str, Any]) -> None:
        error_text = str(event.get("errorText") or "Unknown error")
        self._add_system_message(f"Run error: {error_text}")

    def _handle_text_message_start(self, message_id: str, role: str = "assistant") -> None:
        msg = ChatMessage(role=role)
        if role == "assistant":
            self._current_assistant = msg
        chat = self.query_one("#chat-scroll", VerticalScroll)
        chat.mount(msg)
        self._message_map[message_id] = msg
        self._scroll_to_bottom()

    def _handle_text_message_content(self, message_id: str, delta: str) -> None:
        msg = self._message_map.get(message_id)
        if msg is None:
            msg = ChatMessage(role="assistant")
            chat = self.query_one("#chat-scroll", VerticalScroll)
            chat.mount(msg)
            self._message_map[message_id] = msg
            self._current_assistant = msg
            self._scroll_to_bottom()
        msg.append_content(delta)

    def _handle_thinking_start(self, message_id: str) -> None:
        msg = ChatMessage(role="thinking")
        chat = self.query_one("#chat-scroll", VerticalScroll)
        chat.mount(msg)
        self._message_map[message_id] = msg
        self._current_thinking = msg
        self._scroll_to_bottom()

    def _handle_thinking_delta(self, message_id: str, delta: str) -> None:
        msg = self._message_map.get(message_id)
        if msg is None:
            msg = ChatMessage(role="thinking")
            chat = self.query_one("#chat-scroll", VerticalScroll)
            chat.mount(msg)
            self._message_map[message_id] = msg
            self._current_thinking = msg
            self._scroll_to_bottom()
        msg.append_content(delta)

    def _hydrate_ui_messages(self, messages: list[UIMessage]) -> None:
        for message in messages:
            if message.role == "system":
                content = self._collect_ui_text(message.parts)
                if content:
                    self._add_system_message(content)
                continue
            if message.role == "user":
                content = self._collect_ui_text(message.parts)
                if content:
                    self._add_user_message(content)
                continue
            if message.role == "assistant":
                self._render_assistant_parts(message.parts)

    def _collect_ui_text(self, parts: list[Any]) -> str:
        chunks: list[str] = []
        for part in parts:
            if isinstance(part, TextUIPart):
                if part.text:
                    chunks.append(part.text)
            elif isinstance(part, FileUIPart):
                label = part.filename or part.media_type or "file"
                chunks.append(f"[{label}]")
        return "\n".join(chunks).strip()

    def _render_assistant_parts(self, parts: list[Any]) -> None:
        buffer: list[str] = []

        def flush_buffer() -> None:
            if not buffer:
                return
            content = "".join(buffer).strip()
            buffer.clear()
            if content:
                self._add_assistant_message(content)

        for part in parts:
            if isinstance(part, TextUIPart):
                buffer.append(part.text)
                continue
            if isinstance(part, ReasoningUIPart):
                flush_buffer()
                if part.text:
                    self._add_thinking_message(part.text)
                continue
            if isinstance(part, FileUIPart):
                label = part.filename or part.media_type or "file"
                buffer.append(f"[{label}]")
                continue
            if isinstance(part, ToolInputAvailablePart):
                flush_buffer()
                tool_name = part.type.removeprefix("tool-")
                self._add_tool_call(tool_name, part.input or "", part.tool_call_id)
                continue
            if isinstance(part, ToolOutputAvailablePart):
                flush_buffer()
                tool_name = part.type.removeprefix("tool-")
                self._add_tool_call(tool_name, part.input or "", part.tool_call_id)
                if part.output is not None:
                    self._set_tool_result(part.tool_call_id, part.output)
                continue
            if isinstance(part, ToolOutputErrorPart):
                flush_buffer()
                tool_name = part.type.removeprefix("tool-")
                self._add_tool_call(tool_name, part.input or "", part.tool_call_id)
                self._set_tool_result(part.tool_call_id, {"stderr": part.error_text, "exit_code": 1})
                continue
            if isinstance(part, DynamicToolInputAvailablePart):
                flush_buffer()
                self._add_tool_call(part.tool_name, part.input or "", part.tool_call_id)
                continue
            if isinstance(part, DynamicToolOutputAvailablePart):
                flush_buffer()
                self._add_tool_call(part.tool_name, part.input or "", part.tool_call_id)
                if part.output is not None:
                    self._set_tool_result(part.tool_call_id, part.output)
                continue
            if isinstance(part, DynamicToolOutputErrorPart):
                flush_buffer()
                self._add_tool_call(part.tool_name, part.input or "", part.tool_call_id)
                self._set_tool_result(part.tool_call_id, {"stderr": part.error_text, "exit_code": 1})
                continue

        flush_buffer()

    # -------------------------------------------------------------------------
    # Message Helpers
    # -------------------------------------------------------------------------

    def _reset_message_state(self) -> None:
        self._current_assistant = None
        self._current_thinking = None
        self._tool_calls = {}
        self._message_map = {}

    def _add_user_message(self, content: str) -> None:
        chat = self.query_one("#chat-scroll", VerticalScroll)
        chat.mount(ChatMessage(role="user", content=content))
        self._scroll_to_bottom()

    def _add_assistant_message(self, content: str) -> None:
        chat = self.query_one("#chat-scroll", VerticalScroll)
        msg = ChatMessage(role="assistant", content=content)
        chat.mount(msg)
        self._current_assistant = msg
        self._scroll_to_bottom()

    def _add_thinking_message(self, content: str) -> None:
        chat = self.query_one("#chat-scroll", VerticalScroll)
        msg = ChatMessage(role="thinking", content=content)
        chat.mount(msg)
        self._current_thinking = msg
        self._scroll_to_bottom()

    def _add_system_message(self, content: str) -> None:
        chat = self.query_one("#chat-scroll", VerticalScroll)
        chat.mount(ChatMessage(role="system", content=content))
        self._scroll_to_bottom()

    def _add_tool_call(self, tool_name: str, args: Any, tool_call_id: str) -> None:
        tool_widget = self._tool_calls.get(tool_call_id)
        if tool_widget is None:
            tool_widget = ToolCall(tool_name, args, tool_call_id)
            self._tool_calls[tool_call_id] = tool_widget
            chat = self.query_one("#chat-scroll", VerticalScroll)
            chat.mount(tool_widget)
            self._scroll_to_bottom()
            return

        tool_widget.update_tool_name(tool_name)
        if args:
            payload = args if isinstance(args, str) else json.dumps(args)
            tool_widget.append_args(payload)

    def _append_tool_args(self, tool_call_id: str, delta: str) -> None:
        tool_widget = self._tool_calls.get(tool_call_id)
        if tool_widget is None:
            tool_widget = ToolCall("tool", "", tool_call_id)
            self._tool_calls[tool_call_id] = tool_widget
            chat = self.query_one("#chat-scroll", VerticalScroll)
            chat.mount(tool_widget)
        tool_widget.append_args(delta)

    def _set_tool_result(self, tool_call_id: str, result: Any) -> None:
        if tool_call_id not in self._tool_calls:
            return

        tool_widget = self._tool_calls[tool_call_id]

        data = result
        if hasattr(data, "content"):
            data = data.content
        if hasattr(data, "data"):
            data = data.data

        output = ""
        exit_code = 0
        timed_out = False
        stdout = ""
        stderr = ""

        if hasattr(data, "stdout"):
            stdout = data.stdout or ""
            stderr = data.stderr or ""
            exit_code = data.exit_code
            timed_out = bool(getattr(data, "timed_out", False))
        elif isinstance(data, dict):
            stdout = data.get("stdout", "") or ""
            stderr = data.get("stderr", "") or ""
            exit_code = data.get("exit_code", 0)
            timed_out = bool(data.get("timed_out", False))
        else:
            output = str(data)

        if stdout or stderr:
            if stdout and stderr:
                output = f"{stdout}\\n{stderr}"
            else:
                output = stdout or stderr

        output = self._truncate_output(output)
        tool_widget.set_result(output, exit_code, timed_out=timed_out)

    def _truncate_output(self, output: str, limit: int = 4000) -> str:
        if len(output) <= limit:
            return output
        return output[:limit] + f"\\n... (truncated, {len(output) - limit} chars)"

    def _scroll_to_bottom(self) -> None:
        chat = self.query_one("#chat-scroll", VerticalScroll)
        chat.scroll_end(animate=False)

    def _set_status(self, text: str, streaming: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.update(text)
        status.set_class(streaming, "streaming")

    # -------------------------------------------------------------------------
    # Thread Management
    # -------------------------------------------------------------------------

    async def _thread_exists(self, thread_id: str) -> bool:
        return thread_id in await self.client.list_threads(self.session_id)

    async def _switch_thread(self, new_thread_id: str, *, created: bool = False) -> None:
        self.action_clear_chat()
        await self._load_thread_state(new_thread_id)

        if created:
            self._add_system_message(f"Created thread '{self.thread_id}'.")
        else:
            self._add_system_message(f"Switched to thread '{self.thread_id}'.")

    async def _load_thread_state(self, thread_id: str) -> None:
        self.thread_id = thread_id
        self.agent_id = None
        self.agent_name = None
        self._update_header()
        await self._refresh_agent()
        try:
            payload = await self.client.get_thread_messages(self.session_id, thread_id)
            self._hydrate_ui_messages(payload.messages)
        except Exception as exc:
            self._add_system_message(f"Failed to load history: {exc}")
            return
        self._scroll_to_bottom()

    async def _delete_thread(self, thread_id: str) -> None:
        threads = await self.client.list_threads(self.session_id)

        if thread_id not in threads:
            self._add_system_message(f"Thread '{thread_id}' not found.")
            return

        if thread_id != self.thread_id:
            await self.client.delete_thread(self.session_id, thread_id)
            self._add_system_message(f"Deleted thread '{thread_id}'.")
            return

        await self.client.delete_thread(self.session_id, thread_id)
        remaining = [t for t in threads if t != thread_id]

        if remaining:
            self.action_clear_chat()
            await self._load_thread_state(remaining[0])
            self._add_system_message(
                f"Deleted '{thread_id}'. Switched to '{remaining[0]}'."
            )
        else:
            self.action_clear_chat()
            await self.client.create_thread(self.session_id, "default")
            await self._load_thread_state("default")
            self._add_system_message(f"Deleted '{thread_id}'. Created 'default'.")

    def _update_header(self) -> None:
        if not self._mounted:
            return
        header_left = self.query_one("#header-left", Static)
        header_right = self.query_one("#header-right", Static)

        # Build header parts: thread | agent | model | connection
        parts = [self.thread_id]
        if self.agent_name:
            parts.append(self.agent_name)
        elif self.agent_id:
            parts.append(self.agent_id)
        if self.model_name:
            parts.append(self.model_name)
        if self.connection_info:
            parts.append(self.connection_info.header_label)

        header_left.update(self.agent_name or "Agent")
        header_right.update(" | ".join(parts))


def run_tui(
    *,
    client: AgentClient,
    connection_info: ConnectionInfo | None = None,
) -> None:
    AgentApp(client=client, connection_info=connection_info).run()

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from lattice.cli import ConnectionInfo

from pydantic_ai.ui.vercel_ai.request_types import (
    SubmitMessage,
    TextUIPart,
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
from lattice.tui.rendering import ChatRenderer
from lattice.tui.state import AgentSelectionState, ModelSelectionState


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
        self.agent_state = AgentSelectionState()
        self.model_state = ModelSelectionState()
        self.client = client
        self.connection_info = connection_info
        self._command_suggester = CommandSuggester(
            model_provider=self._get_model_suggestions,
            agent_provider=self._get_agent_suggestions,
        )

        self._renderer = ChatRenderer(
            get_chat=self._get_chat_container,
            scroll_to_bottom=self._scroll_to_bottom,
        )
        self._worker = None
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
            bootstrap = await self.client.bootstrap_session()
        except Exception as exc:
            self._add_system_message(f"Failed to load session: {exc}")
            return

        self.session_id = bootstrap.session_id
        self.action_clear_chat()
        self._apply_thread_state(bootstrap)
        self._scroll_to_bottom()

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
        chat = self._get_chat_container()
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
        if value.startswith("/model") and self.model_state.cache is None and not self.model_state.loading:
            self.run_worker(self._prefetch_models(), exclusive=False)
        if value.startswith("/agent") and self.agent_state.cache is None and not self.agent_state.loading:
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
            if self.agent_state.current_name and self.agent_state.current_id:
                self._add_system_message(
                    f"Current agent: {self.agent_state.current_name} ({self.agent_state.current_id})"
                )
            else:
                self._add_system_message(f"Current agent: {self.agent_state.current_id or '(unknown)'}")
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
            current = self.model_state.current or "(unknown)"
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
        if self.model_state.cache is not None:
            return self.model_state.cache
        if self.model_state.loading:
            return self.model_state.cache or []
        self.model_state.loading = True
        try:
            payload = await self.client.list_thread_models(self.session_id, self.thread_id)
        except Exception as exc:
            self._add_system_message(f"Failed to load models: {exc}")
            self.model_state.loading = False
            return []
        self.model_state.cache = payload.models
        self.model_state.default = payload.default_model
        self.model_state.loading = False
        return self.model_state.cache

    async def _prefetch_models(self) -> None:
        await self._load_models()

    def _get_model_suggestions(self) -> list[str]:
        return self.model_state.cache or []

    async def _load_agents(self) -> list[tuple[str, str]]:
        if self.agent_state.cache is not None:
            return self.agent_state.cache
        if self.agent_state.loading:
            return self.agent_state.cache or []
        self.agent_state.loading = True
        try:
            payload = await self.client.list_agents()
        except Exception as exc:
            self._add_system_message(f"Failed to load agents: {exc}")
            self.agent_state.loading = False
            return []
        self.agent_state.cache = [(agent.id, agent.name) for agent in payload.agents]
        self.agent_state.default_id = payload.default_agent
        self.agent_state.loading = False
        return self.agent_state.cache

    async def _prefetch_agents(self) -> None:
        await self._load_agents()

    def _get_agent_suggestions(self) -> list[str]:
        if not self.agent_state.cache:
            return []
        return [agent_id for agent_id, _ in self.agent_state.cache]

    async def _refresh_thread_state(self) -> bool:
        try:
            state = await self.client.get_thread_state(self.session_id, self.thread_id)
        except Exception as exc:
            self._add_system_message(f"Failed to load thread state: {exc}")
            return False
        self._apply_thread_selection(state)
        return True

    async def _refresh_agent(self) -> None:
        if not await self._refresh_thread_state():
            return

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
            state = await self.client.update_thread_state(
                self.session_id,
                self.thread_id,
                agent=agent_id,
            )
        except Exception as exc:
            self._add_system_message(f"Failed to set agent: {exc}")
            return
        self._apply_thread_selection(state)

        label = self.agent_state.label()
        if state.agent.is_default:
            self._add_system_message(f"Agent reset to default: {label}")
        else:
            self._add_system_message(f"Agent set to: {label}")

    async def _refresh_model(self) -> None:
        if not await self._refresh_thread_state():
            return

    async def _set_session_model(self, model_name: str | None) -> None:
        try:
            state = await self.client.update_thread_state(
                self.session_id,
                self.thread_id,
                model=model_name,
            )
        except Exception as exc:
            self._add_system_message(f"Failed to set model: {exc}")
            return
        self._apply_thread_selection(state)
        if state.model.is_default:
            self._add_system_message(f"Model reset to default: {state.model.model}")
        else:
            self._add_system_message(f"Model set to: {state.model.model}")

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
        self._renderer.handle_text_start(message_id)

    def _on_text_delta_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("id") or "")
        delta = str(event.get("delta") or "")
        if message_id:
            self._renderer.handle_text_delta(message_id, delta)

    def _on_reasoning_start_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("id") or uuid4().hex)
        self._renderer.handle_thinking_start(message_id)

    def _on_reasoning_delta_event(self, event: dict[str, Any]) -> None:
        message_id = str(event.get("id") or "")
        delta = str(event.get("delta") or "")
        if message_id:
            self._renderer.handle_thinking_delta(message_id, delta)

    def _on_tool_input_start_event(self, event: dict[str, Any]) -> None:
        self._handle_tool_input_event(event, include_args=False)

    def _on_tool_input_delta_event(self, event: dict[str, Any]) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        delta = str(event.get("inputTextDelta") or "")
        if tool_call_id and delta:
            self._renderer.append_tool_args(tool_call_id, delta)

    def _on_tool_input_available_event(self, event: dict[str, Any]) -> None:
        self._handle_tool_input_event(event, include_args=True)

    def _handle_tool_input_event(self, event: dict[str, Any], *, include_args: bool) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        if not tool_call_id:
            return
        tool_name = str(event.get("toolName") or "tool")
        args = event.get("input") if include_args else ""
        self._renderer.add_tool_call(tool_name, args, tool_call_id)

    def _on_tool_output_available_event(self, event: dict[str, Any]) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        if tool_call_id:
            self._renderer.set_tool_result(tool_call_id, event.get("output"))

    def _on_tool_output_error_event(self, event: dict[str, Any]) -> None:
        tool_call_id = str(event.get("toolCallId") or "")
        error_text = str(event.get("errorText") or "Tool error")
        if tool_call_id:
            self._renderer.set_tool_result(tool_call_id, {"stderr": error_text, "exit_code": 1})

    def _on_error_event(self, event: dict[str, Any]) -> None:
        error_text = str(event.get("errorText") or "Unknown error")
        self._add_system_message(f"Run error: {error_text}")

    # -------------------------------------------------------------------------
    # Message Helpers
    # -------------------------------------------------------------------------

    def _reset_message_state(self) -> None:
        self._renderer.reset()

    def _add_user_message(self, content: str) -> None:
        self._renderer.add_user_message(content)

    def _add_assistant_message(self, content: str) -> None:
        self._renderer.add_assistant_message(content)

    def _add_thinking_message(self, content: str) -> None:
        self._renderer.add_thinking_message(content)

    def _add_system_message(self, content: str) -> None:
        self._renderer.add_system_message(content)

    def _hydrate_ui_messages(self, messages: list[UIMessage]) -> None:
        self._renderer.hydrate_ui_messages(messages)

    def _scroll_to_bottom(self) -> None:
        chat = self._get_chat_container()
        chat.scroll_end(animate=False)

    def _get_chat_container(self) -> VerticalScroll:
        return self.query_one("#chat-scroll", VerticalScroll)

    def _set_status(self, text: str, streaming: bool = False) -> None:
        status = self.query_one("#status", Static)
        status.update(text)
        status.set_class(streaming, "streaming")

    # -------------------------------------------------------------------------
    # Thread Management
    # -------------------------------------------------------------------------

    def _apply_thread_selection(self, state) -> None:
        previous_thread = self.thread_id
        previous_agent = self.agent_state.current_id
        self.thread_id = state.thread_id
        self.agent_state.current_id = state.agent.agent
        self.agent_state.current_name = state.agent.agent_name
        self.agent_state.default_id = state.agent.default_agent
        self.model_state.current = state.model.model
        self.model_state.default = state.model.default_model
        if self.thread_id != previous_thread or self.agent_state.current_id != previous_agent:
            self.model_state.cache = None
            self.model_state.loading = False
        self._update_header()

    def _apply_thread_state(self, state) -> None:
        self._apply_thread_selection(state)
        self._hydrate_ui_messages(state.messages)

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
        self.agent_state.current_id = None
        self.agent_state.current_name = None
        self._update_header()
        try:
            state = await self.client.get_thread_state(self.session_id, thread_id)
            self._apply_thread_state(state)
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
            self._add_system_message(f"Deleted '{thread_id}'. Switched to '{remaining[0]}'.")
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
        if self.agent_state.current_name:
            parts.append(self.agent_state.current_name)
        elif self.agent_state.current_id:
            parts.append(self.agent_state.current_id)
        if self.model_state.current:
            parts.append(self.model_state.current)
        if self.connection_info:
            parts.append(self.connection_info.header_label)

        header_left.update(self.agent_state.current_name or "Agent")
        header_right.update(" | ".join(parts))


def run_tui(
    *,
    client: AgentClient,
    connection_info: ConnectionInfo | None = None,
) -> None:
    AgentApp(client=client, connection_info=connection_info).run()

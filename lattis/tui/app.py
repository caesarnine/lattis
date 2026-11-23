from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lattis.cli import ConnectionInfo

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Input, Static

from lattis.client import AgentClient
from lattis.domain.models import GLOBAL_WORKSPACE_ID, generate_thread_id
from lattis.protocol.schemas import (
    BusResyncRequiredEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunFailedEvent,
    RunStartedEvent,
    RunWaitingApprovalEvent,
    ThreadClearedEvent,
    ThreadResponse,
    ThreadUpdatedEvent,
)
from lattis.tui.commands import CommandSuggester, ParsedCommand, build_help_text, parse_command
from lattis.tui.rendering import ChatRenderer
from lattis.tui.state import AgentSelectionState, ModelSelectionState


class AgentApp(App):
    """Terminal client for the Lattis v2 daemon."""

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
        project_root: Path | None = None,
        default_agent: str | None = None,
    ):
        super().__init__()
        self.workspace_id = GLOBAL_WORKSPACE_ID
        self.workspace_name = "Global"
        self.thread_id = "..."
        self.active_run_id: str | None = None
        self.agent_state = AgentSelectionState()
        self.model_state = ModelSelectionState()
        self.client = client
        self.connection_info = connection_info
        self._project_root = project_root
        self._default_agent = default_agent
        self._command_suggester = CommandSuggester(
            model_provider=self._get_model_suggestions,
            agent_provider=self._get_agent_suggestions,
        )
        self._renderer = ChatRenderer(
            get_chat=self._get_chat_container,
            scroll_to_bottom=self._scroll_to_bottom,
        )
        self._events_worker = None
        self._last_seq: int | None = None
        self._mounted = False

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
            if self._project_root is not None:
                ws = await self.client.register_workspace(str(self._project_root))
            else:
                ws = await self.client.get_workspace(GLOBAL_WORKSPACE_ID)
            self.workspace_id = ws.id
            self.workspace_name = ws.name

            threads = await self.client.list_threads(self.workspace_id)
            if threads:
                active_thread = threads[0]
            else:
                active_thread = await self.client.create_thread(
                    self.workspace_id,
                    agent_id=self._default_agent,
                )
        except Exception as exc:
            self._add_system_message(f"Failed to connect to daemon: {exc}")
            return

        self.action_clear_chat()
        self._apply_thread(active_thread)
        await self._hydrate_current_thread()
        self._events_worker = self.run_worker(self._subscribe_events(), exclusive=False)

    async def on_shutdown(self) -> None:
        if self._events_worker is not None:
            self._events_worker.cancel()
        await self.client.close()

    # -------------------------------------------------------------------------
    # Event Bus Subscription
    # -------------------------------------------------------------------------

    async def _subscribe_events(self) -> None:
        while True:
            try:
                async for event in self.client.iter_events(
                    workspace_id=self.workspace_id,
                    after_seq=self._last_seq,
                ):
                    self._last_seq = event.seq
                    if isinstance(event, BusResyncRequiredEvent):
                        await self._reload_current_thread()
                        continue
                    if event.thread_id != self.thread_id:
                        continue
                    if isinstance(event, ThreadUpdatedEvent):
                        self._apply_thread(event.data)
                        continue
                    if isinstance(event, ThreadClearedEvent):
                        self.action_clear_chat()
                        continue
                    if isinstance(event, RunStartedEvent):
                        self.active_run_id = event.data.id
                        self._set_status("running", streaming=True)
                        continue
                    if isinstance(event, RunWaitingApprovalEvent):
                        self.active_run_id = event.data.run.id
                        self._set_status("approval", streaming=True)
                        continue
                    if isinstance(event, (RunCompletedEvent, RunCancelledEvent, RunFailedEvent)):
                        if self.active_run_id == event.data.id:
                            self.active_run_id = None
                        self._set_status("")
                    self._renderer.handle_event(event)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(1.0)

    # -------------------------------------------------------------------------
    # Actions
    # -------------------------------------------------------------------------

    def action_cancel_run(self) -> None:
        if self.active_run_id:
            run_id = self.active_run_id
            self.run_worker(self._cancel_active_run(run_id), exclusive=False)

    async def _cancel_active_run(self, run_id: str) -> None:
        try:
            await self.client.cancel_run(run_id)
        except Exception as exc:
            self._add_system_message(f"Failed to cancel run: {exc}")

    def action_clear_chat(self) -> None:
        chat = self._get_chat_container()
        chat.remove_children()
        self._renderer.reset()

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

        try:
            created = await self.client.start_run(self.thread_id, user_input)
            self.active_run_id = created.run.id
            self._renderer.render_item(created.user_item)
            self._set_status("running", streaming=True)
        except Exception as exc:
            self._add_system_message(f"Run error: {exc}")

    @on(Input.Changed, "#input")
    async def handle_input_changed(self, event: Input.Changed) -> None:
        value = event.value.strip()
        if value.startswith("/model") and self.model_state.cache is None and not self.model_state.loading:
            self.run_worker(self._load_models(), exclusive=False)
        if value.startswith("/agent") and self.agent_state.cache is None and not self.agent_state.loading:
            self.run_worker(self._load_agents(), exclusive=False)

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
            threads = await self.client.list_threads(self.workspace_id)
            if not threads:
                self._add_system_message("Threads: (none)")
            else:
                lines = [
                    f"- {t.id}" + (f" ({t.title})" if t.title else "") + (f" [{t.status}]" if t.status != "idle" else "")
                    for t in threads
                ]
                self._add_system_message("Threads:\n" + "\n".join(lines))
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
            self._add_system_message(f"Current thread: {self.thread_id} (workspace: {self.workspace_name})")
            return

        subcommand = parts[0].lower()
        if subcommand in {"new", "create"}:
            new_id = parts[1].strip() if len(parts) > 1 else generate_thread_id()
            try:
                created = await self.client.create_thread(
                    self.workspace_id,
                    thread_id=new_id,
                    agent_id=self._default_agent,
                )
            except Exception as exc:
                self._add_system_message(f"Failed to create thread '{new_id}': {exc}")
                return
            await self._switch_thread(created, created=True)
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
        try:
            thread = await self.client.get_thread(target)
            created_flag = False
        except Exception:
            try:
                thread = await self.client.create_thread(
                    self.workspace_id,
                    thread_id=target,
                    agent_id=self._default_agent,
                )
                created_flag = True
            except Exception as exc:
                self._add_system_message(f"Failed to open thread '{target}': {exc}")
                return
        await self._switch_thread(thread, created=created_flag)

    async def _handle_agent_command(self, command: ParsedCommand) -> None:
        parts = command.args
        if not parts or parts[0].lower() in {"current", "show"}:
            await self._refresh_thread()
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
            matches = (
                [(aid, name) for aid, name in agents if needle in aid.lower() or needle in name.lower()]
                if query
                else agents
            )
            if not matches:
                self._add_system_message(f"No agents found for '{query}'.")
                return
            lines = [f"Agents ({len(matches)}):"]
            for i, (agent_id, name) in enumerate(matches[:30], start=1):
                label = f"{name} — {agent_id}" if name and name != agent_id else agent_id
                lines.append(f"{i}. {label}")
            self._add_system_message("\n".join(lines))
            return

        if subcommand in {"default", "reset"}:
            await self._set_thread_agent(None)
            return

        value = " ".join(parts[1:] if subcommand == "set" else parts).strip()
        if not value:
            self._add_system_message("Usage: /agent set <agent-id|number>")
            return
        agent_id = await self._resolve_agent_id(value)
        if agent_id is not None:
            await self._set_thread_agent(agent_id)

    async def _handle_model_command(self, command: ParsedCommand) -> None:
        parts = command.args
        if not parts or parts[0].lower() in {"current", "show"}:
            await self._refresh_thread()
            self._add_system_message(f"Current model: {self.model_state.current or '(unknown)'}")
            return

        subcommand = parts[0].lower()
        if subcommand == "list":
            query = " ".join(parts[1:]).strip()
            models = await self._load_models()
            matches = [m for m in models if query.lower() in m.lower()] if query else models
            if not matches:
                self._add_system_message(f"No models found for '{query}'.")
                return
            shown = matches[:30]
            lines = [f"Models ({len(matches)}):", *[f"- {m}" for m in shown]]
            if len(matches) > 30:
                lines.append("... showing first 30. Use /model list <filter> to narrow.")
            self._add_system_message("\n".join(lines))
            return

        if subcommand in {"default", "reset"}:
            await self._set_thread_model(None)
            return

        model_name = " ".join(parts[1:] if subcommand == "set" else parts).strip()
        if not model_name:
            self._add_system_message("Usage: /model set <model-name>")
            return
        await self._set_thread_model(model_name)

    async def _load_models(self) -> list[str]:
        if self.model_state.cache is not None:
            return self.model_state.cache
        if self.model_state.loading:
            return self.model_state.cache or []
        self.model_state.loading = True
        try:
            payload = await self.client.list_thread_models(self.thread_id)
        except Exception as exc:
            self._add_system_message(f"Failed to load models: {exc}")
            self.model_state.loading = False
            return []
        self.model_state.cache = payload.models
        self.model_state.default = payload.default_model
        self.model_state.loading = False
        return self.model_state.cache

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
        self.agent_state.cache = [(a.id, a.name) for a in payload.agents]
        self.agent_state.default_id = payload.default_agent
        self.agent_state.loading = False
        return self.agent_state.cache

    def _get_agent_suggestions(self) -> list[str]:
        if not self.agent_state.cache:
            return []
        return [agent_id for agent_id, _ in self.agent_state.cache]

    async def _resolve_agent_id(self, value: str) -> str | None:
        if value.isdigit():
            idx = int(value)
            agents = await self._load_agents()
            if idx <= 0 or idx > len(agents):
                self._add_system_message(f"Agent number out of range (1-{len(agents)}).")
                return None
            return agents[idx - 1][0]
        return value

    async def _refresh_thread(self) -> None:
        try:
            thread = await self.client.get_thread(self.thread_id)
        except Exception as exc:
            self._add_system_message(f"Failed to load thread: {exc}")
            return
        self._apply_thread(thread)

    async def _set_thread_agent(self, agent_id: str | None) -> None:
        try:
            thread = await self.client.update_thread(self.thread_id, agent_id=agent_id)
        except Exception as exc:
            self._add_system_message(f"Failed to set agent: {exc}")
            return
        self._apply_thread(thread)
        label = self.agent_state.label()
        if thread.resolved_agent.is_default:
            self._add_system_message(f"Agent reset to default: {label}")
        else:
            self._add_system_message(f"Agent set to: {label}")

    async def _set_thread_model(self, model_name: str | None) -> None:
        try:
            thread = await self.client.update_thread(self.thread_id, model=model_name)
        except Exception as exc:
            self._add_system_message(f"Failed to set model: {exc}")
            return
        self._apply_thread(thread)
        if thread.resolved_model.is_default:
            self._add_system_message(f"Model reset to default: {thread.resolved_model.model}")
        else:
            self._add_system_message(f"Model set to: {thread.resolved_model.model}")

    async def _clear_current_thread(self) -> None:
        self.action_clear_chat()
        try:
            await self.client.clear_thread(self.thread_id)
        except Exception as exc:
            self._add_system_message(f"Failed to clear thread: {exc}")

    # -------------------------------------------------------------------------
    # Thread Management & Rendering Helpers
    # -------------------------------------------------------------------------

    def _apply_thread(self, thread: ThreadResponse) -> None:
        previous_thread = self.thread_id
        previous_agent = self.agent_state.current_id
        self.thread_id = thread.id
        self.active_run_id = thread.active_run_id
        self.agent_state.current_id = thread.resolved_agent.agent
        self.agent_state.current_name = thread.resolved_agent.agent_name
        self.agent_state.default_id = thread.resolved_agent.default_agent
        self.model_state.current = thread.resolved_model.model
        self.model_state.default = thread.resolved_model.default_model
        if self.thread_id != previous_thread or self.agent_state.current_id != previous_agent:
            self.model_state.cache = None
            self.model_state.loading = False
        if thread.status == "running":
            self._set_status("running", streaming=True)
        elif thread.status == "waiting_approval":
            self._set_status("approval", streaming=True)
        else:
            self._set_status("")
        self._update_header()

    async def _hydrate_current_thread(self) -> None:
        try:
            listing = await self.client.list_thread_items(self.thread_id)
            self._renderer.hydrate_items(listing.items)
        except Exception as exc:
            self._add_system_message(f"Failed to load history: {exc}")
        self._scroll_to_bottom()

    async def _reload_current_thread(self) -> None:
        self.action_clear_chat()
        await self._refresh_thread()
        await self._hydrate_current_thread()

    async def _switch_thread(self, thread: ThreadResponse, *, created: bool = False) -> None:
        self.action_clear_chat()
        self._apply_thread(thread)
        await self._hydrate_current_thread()
        if created:
            self._add_system_message(f"Created thread '{self.thread_id}'.")
        else:
            self._add_system_message(f"Switched to thread '{self.thread_id}'.")

    async def _delete_thread(self, thread_id: str) -> None:
        try:
            await self.client.delete_thread(thread_id)
        except Exception as exc:
            self._add_system_message(f"Failed to delete thread '{thread_id}': {exc}")
            return

        if thread_id != self.thread_id:
            self._add_system_message(f"Deleted thread '{thread_id}'.")
            return

        threads = await self.client.list_threads(self.workspace_id)
        if threads:
            await self._switch_thread(threads[0])
            self._add_system_message(f"Deleted '{thread_id}'. Switched to '{threads[0].id}'.")
        else:
            created = await self.client.create_thread(self.workspace_id, agent_id=self._default_agent)
            await self._switch_thread(created, created=True)
            self._add_system_message(f"Deleted '{thread_id}'. Created '{created.id}'.")

    def _add_system_message(self, content: str) -> None:
        self._renderer.add_system_message(content)

    def _scroll_to_bottom(self) -> None:
        self._get_chat_container().scroll_end(animate=False)

    def _get_chat_container(self) -> VerticalScroll:
        return self.query_one("#chat-scroll", VerticalScroll)

    def _set_status(self, text: str, streaming: bool = False) -> None:
        if not self._mounted:
            return
        status = self.query_one("#status", Static)
        status.update(text)
        status.set_class(streaming, "streaming")

    def _update_header(self) -> None:
        if not self._mounted:
            return
        header_left = self.query_one("#header-left", Static)
        header_right = self.query_one("#header-right", Static)

        parts = [self.workspace_name, self.thread_id]
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
    project_root: Path | None = None,
    default_agent: str | None = None,
) -> None:
    AgentApp(
        client=client,
        connection_info=connection_info,
        project_root=project_root,
        default_agent=default_agent,
    ).run()

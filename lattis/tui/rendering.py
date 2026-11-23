from __future__ import annotations

import json
from typing import Any, Callable

from textual.containers import VerticalScroll

from lattis.protocol.schemas import (
    ItemCompletedEvent,
    ItemCreatedEvent,
    ItemDeltaEvent,
    ItemResponse,
    LattisEvent,
    RunCancelledEvent,
    RunFailedEvent,
)
from lattis.tui.widgets import ChatMessage, ToolCall


class ChatRenderer:
    """Renders normalized Lattis v2 items and live SSE events into Textual widgets."""

    def __init__(
        self,
        *,
        get_chat: Callable[[], VerticalScroll],
        scroll_to_bottom: Callable[[], None],
    ) -> None:
        self._get_chat = get_chat
        self._scroll_to_bottom = scroll_to_bottom
        self._messages: dict[str, ChatMessage] = {}
        self._tools: dict[str, ToolCall] = {}

    def reset(self) -> None:
        self._messages = {}
        self._tools = {}

    def add_user_message(self, content: str, *, item_id: str | None = None) -> None:
        if item_id and item_id in self._messages:
            return
        widget = ChatMessage(role="user", content=content)
        self._get_chat().mount(widget)
        if item_id:
            self._messages[item_id] = widget
        self._scroll_to_bottom()

    def add_assistant_message(self, content: str, *, item_id: str | None = None) -> None:
        if item_id and item_id in self._messages:
            return
        widget = ChatMessage(role="assistant", content=content)
        self._get_chat().mount(widget)
        if item_id:
            self._messages[item_id] = widget
        self._scroll_to_bottom()

    def add_thinking_message(self, content: str, *, item_id: str | None = None) -> None:
        if item_id and item_id in self._messages:
            return
        widget = ChatMessage(role="thinking", content=content)
        self._get_chat().mount(widget)
        if item_id:
            self._messages[item_id] = widget
        self._scroll_to_bottom()

    def add_system_message(self, content: str, *, item_id: str | None = None) -> None:
        if item_id and item_id in self._messages:
            return
        widget = ChatMessage(role="system", content=content)
        self._get_chat().mount(widget)
        if item_id:
            self._messages[item_id] = widget
        self._scroll_to_bottom()

    def hydrate_items(self, items: list[ItemResponse]) -> None:
        for item in items:
            self.render_item(item)

    def render_item(self, item: ItemResponse) -> None:
        payload = item.payload
        if item.kind == "user_message":
            self.add_user_message(str(payload.get("text") or ""), item_id=item.id)
            return
        if item.kind == "assistant_text":
            self.add_assistant_message(str(payload.get("text") or ""), item_id=item.id)
            return
        if item.kind == "reasoning":
            self.add_thinking_message(str(payload.get("text") or ""), item_id=item.id)
            return
        if item.kind == "system_note":
            self.add_system_message(str(payload.get("text") or ""), item_id=item.id)
            return
        if item.kind == "approval_request":
            tool_name = str(payload.get("tool_name") or "tool")
            approval_id = str(payload.get("approval_id") or item.id)
            decision = payload.get("decision")
            if decision:
                self.add_system_message(f"Approval {approval_id} ({tool_name}): {decision}", item_id=item.id)
            else:
                self.add_system_message(
                    f"Approval required ({approval_id}) for tool '{tool_name}'.",
                    item_id=item.id,
                )
            return
        if item.kind == "tool_call":
            self._upsert_tool_item(item)

    def handle_event(self, event: LattisEvent) -> None:
        if isinstance(event, ItemCreatedEvent):
            self.render_item(event.data)
            return

        if isinstance(event, ItemDeltaEvent):
            data = event.data
            if data.channel == "text":
                msg = self._messages.get(data.item_id)
                if msg is None:
                    msg = ChatMessage(role="assistant")
                    self._get_chat().mount(msg)
                    self._messages[data.item_id] = msg
                msg.append_content(data.delta)
                self._scroll_to_bottom()
                return
            if data.channel == "reasoning":
                msg = self._messages.get(data.item_id)
                if msg is None:
                    msg = ChatMessage(role="thinking")
                    self._get_chat().mount(msg)
                    self._messages[data.item_id] = msg
                msg.append_content(data.delta)
                self._scroll_to_bottom()
                return
            if data.channel == "tool_input":
                tool = self._tools.get(data.item_id)
                if tool is not None:
                    tool.append_args(data.delta)
                return
            if data.channel == "tool_output":
                tool = self._tools.get(data.item_id)
                if tool is not None:
                    tool.append_output(data.delta)
                    self._scroll_to_bottom()
                return
            return

        if isinstance(event, ItemCompletedEvent):
            self._finalize_item(event.data)
            return

        if isinstance(event, RunFailedEvent):
            err = event.data.error or "Unknown error"
            self.add_system_message(f"Run failed: {err}")
            return

        if isinstance(event, RunCancelledEvent):
            self.add_system_message("Run cancelled.")

    def _upsert_tool_item(self, item: ItemResponse) -> None:
        payload = item.payload
        tool_name = str(payload.get("tool_name") or "tool")
        args = payload.get("args") or payload.get("args_raw") or ""
        tool_call_id = str(payload.get("tool_call_id") or item.id)

        widget = self._tools.get(item.id)
        if widget is None:
            widget = ToolCall(tool_name, args, tool_call_id)
            self._tools[item.id] = widget
            self._get_chat().mount(widget)
            self._scroll_to_bottom()
        else:
            widget.update_tool_name(tool_name)
            if args:
                raw = args if isinstance(args, str) else json.dumps(args)
                widget.append_args(raw)

        if payload.get("result") is not None or item.status in {"completed", "error", "cancelled"}:
            self._apply_tool_result(widget, payload)
        elif payload.get("output_stream"):
            widget.append_output(str(payload["output_stream"]))

    def _finalize_item(self, item: ItemResponse) -> None:
        if item.kind == "tool_call":
            self._upsert_tool_item(item)
            return
        if item.kind in {"assistant_text", "reasoning"}:
            widget = self._messages.get(item.id)
            text = str(item.payload.get("text") or "")
            if widget is None:
                self.render_item(item)
            elif text and widget.content != text:
                widget.content = ""
                widget.append_content(text)
            return
        if item.kind == "approval_request":
            decision = item.payload.get("decision")
            tool_name = item.payload.get("tool_name") or "tool"
            if decision:
                self.add_system_message(f"Approval ({tool_name}): {decision}")

    def _apply_tool_result(self, widget: ToolCall, payload: dict[str, Any]) -> None:
        result = payload.get("result")
        output = ""
        exit_code = 1 if payload.get("is_error") else 0
        timed_out = False

        if isinstance(result, dict):
            stdout = result.get("stdout", "") or ""
            stderr = result.get("stderr", "") or ""
            exit_code = int(result.get("exit_code", exit_code))
            timed_out = bool(result.get("timed_out", False))
            if stdout and stderr:
                output = f"{stdout}\n{stderr}"
            else:
                output = stdout or stderr or (json.dumps(result) if not ("stdout" in result or "stderr" in result) else "")
        elif result is not None:
            output = str(result)
        elif payload.get("output_stream"):
            output = str(payload["output_stream"])

        output = self._truncate_output(output)
        widget.set_result(output, exit_code, timed_out=timed_out)

    @staticmethod
    def _truncate_output(output: str, limit: int = 4000) -> str:
        if len(output) <= limit:
            return output
        return output[:limit] + f"\n... (truncated, {len(output) - limit} chars)"

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage

from lattis.client import AgentClient

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
DEFAULT_TELEGRAM_SESSION_ID = "telegram-bot"
DEFAULT_TELEGRAM_THREAD_PREFIX = "tg"


@dataclass(frozen=True)
class TelegramBotConfig:
    token: str
    session_id: str = DEFAULT_TELEGRAM_SESSION_ID
    thread_prefix: str = DEFAULT_TELEGRAM_THREAD_PREFIX
    poll_timeout: int = 30
    telegram_api_base: str = "https://api.telegram.org"

    @property
    def telegram_base_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/bot{self.token}"


@dataclass
class StreamTextAccumulator:
    _order: list[str] = field(default_factory=list)
    _chunks: dict[str, list[str]] = field(default_factory=dict)

    def add(self, event: dict[str, object]) -> None:
        event_type = event.get("type")
        if not isinstance(event_type, str):
            return
        if event_type == "error":
            detail = event.get("errorText")
            message = str(detail) if detail else "Unknown error"
            raise RuntimeError(message)
        if event_type == "text-start":
            message_id = _as_non_empty_string(event.get("id"))
            if message_id:
                self._ensure(message_id)
            return
        if event_type == "text-delta":
            message_id = _as_non_empty_string(event.get("id"))
            delta = event.get("delta")
            if message_id and isinstance(delta, str) and delta:
                self._ensure(message_id)
                self._chunks[message_id].append(delta)

    def render(self) -> str:
        parts: list[str] = []
        for message_id in self._order:
            content = "".join(self._chunks.get(message_id, []))
            value = content.strip()
            if value:
                parts.append(value)
        return "\n\n".join(parts)

    def _ensure(self, message_id: str) -> None:
        if message_id in self._chunks:
            return
        self._chunks[message_id] = []
        self._order.append(message_id)


class TelegramBotBridge:
    def __init__(
        self,
        *,
        config: TelegramBotConfig,
        agent_client: AgentClient,
        telegram_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.agent_client = agent_client
        self._telegram_client = telegram_client or httpx.AsyncClient(
            base_url=config.telegram_base_url,
            timeout=httpx.Timeout(40.0, connect=10.0),
        )
        self._owns_telegram_client = telegram_client is None
        self._chat_locks: dict[int, asyncio.Lock] = {}
        self._known_threads: set[str] = set()
        self._offset: int | None = None

    async def close(self) -> None:
        if self._owns_telegram_client:
            await self._telegram_client.aclose()

    async def run_forever(self) -> None:
        logger.info(
            "starting telegram bridge session=%s thread_prefix=%s",
            self.config.session_id,
            self.config.thread_prefix,
        )
        try:
            while True:
                try:
                    updates = await self._poll_updates()
                except Exception:
                    logger.exception("telegram poll failed")
                    await asyncio.sleep(1.0)
                    continue
                for update in updates:
                    try:
                        await self._handle_update(update)
                    except Exception:
                        logger.exception("telegram update handling failed")
        finally:
            await self.close()

    async def _poll_updates(self) -> list[dict[str, object]]:
        payload: dict[str, object] = {
            "timeout": max(self.config.poll_timeout, 1),
            "allowed_updates": ["message"],
        }
        if self._offset is not None:
            payload["offset"] = self._offset
        response = await self._telegram_request("getUpdates", payload)
        result = response.get("result")
        if not isinstance(result, list):
            return []
        updates = [item for item in result if isinstance(item, dict)]
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self._offset = update_id + 1
        return updates

    async def _handle_update(self, update: dict[str, object]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        sender = message.get("from")
        if isinstance(sender, dict) and sender.get("is_bot") is True:
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return
        text = message.get("text")
        if not isinstance(text, str):
            return
        incoming_text = text.strip()
        if not incoming_text:
            return

        lock = self._chat_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            await self._handle_chat_text(chat_id, incoming_text)

    async def _handle_chat_text(self, chat_id: int, text: str) -> None:
        thread_id = thread_id_for_chat(chat_id, prefix=self.config.thread_prefix)
        await self._ensure_thread(thread_id)

        if text in {"/start", "/help"}:
            await self._send_message(
                chat_id,
                (
                    "Connected to Lattis.\n"
                    f"This chat uses thread '{thread_id}'.\n"
                    "Send a message to chat with the active agent.\n"
                    "Use /clear to reset this thread."
                ),
            )
            return

        if text in {"/clear", "/reset"}:
            await self.agent_client.clear_thread(self.config.session_id, thread_id)
            await self._send_message(chat_id, "Cleared this thread.")
            return

        try:
            await self._send_typing(chat_id)
            run_input = build_run_input(text=text, session_id=self.config.session_id, thread_id=thread_id)
            response_text = await collect_assistant_text(self.agent_client.run_stream(run_input))
            if not response_text:
                response_text = "(No assistant text returned.)"
            await self._send_message(chat_id, response_text)
        except Exception as exc:
            logger.exception("telegram run failed chat_id=%s thread_id=%s", chat_id, thread_id)
            await self._send_message(chat_id, f"Run error: {exc}")

    async def _ensure_thread(self, thread_id: str) -> None:
        if thread_id in self._known_threads:
            return
        try:
            await self.agent_client.create_thread(self.config.session_id, thread_id)
        except RuntimeError as exc:
            detail = str(exc).lower()
            if "already exists" not in detail:
                raise
        self._known_threads.add(thread_id)

    async def _send_typing(self, chat_id: int) -> None:
        try:
            await self._telegram_request("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        except Exception:
            logger.debug("failed to send typing indicator", exc_info=True)

    async def _send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_telegram_message(text):
            await self._telegram_request(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                },
            )

    async def _telegram_request(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        response = await self._telegram_client.post(f"/{method}", json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Telegram API '{method}' returned invalid payload.")
        if data.get("ok") is not True:
            detail = data.get("description")
            message = str(detail) if detail else f"Telegram API '{method}' failed."
            raise RuntimeError(message)
        return data


def _as_non_empty_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def build_run_input(*, text: str, session_id: str, thread_id: str) -> SubmitMessage:
    return SubmitMessage(
        id=uuid4().hex,
        messages=[
            UIMessage(
                id=uuid4().hex,
                role="user",
                parts=[TextUIPart(text=text)],
            )
        ],
        session_id=session_id,
        thread_id=thread_id,
    )


async def collect_assistant_text(events: AsyncIterator[dict[str, object]]) -> str:
    accumulator = StreamTextAccumulator()
    async for event in events:
        accumulator.add(event)
    return accumulator.render()


def split_telegram_message(
    text: str,
    *,
    max_length: int = TELEGRAM_MAX_MESSAGE_LENGTH,
) -> list[str]:
    if max_length <= 0:
        raise ValueError("max_length must be greater than zero.")
    remaining = text.strip()
    if not remaining:
        return []
    if len(remaining) <= max_length:
        return [remaining]

    chunks: list[str] = []
    while remaining:
        if len(remaining) <= max_length:
            chunks.append(remaining)
            break

        cut_index = remaining.rfind("\n", 0, max_length + 1)
        if cut_index <= 0:
            cut_index = remaining.rfind(" ", 0, max_length + 1)
        if cut_index <= 0:
            cut_index = max_length

        chunk = remaining[:cut_index].rstrip()
        if not chunk:
            chunk = remaining[:max_length]
            cut_index = max_length

        chunks.append(chunk)
        remaining = remaining[cut_index:].lstrip()

    return chunks


def thread_id_for_chat(chat_id: int, *, prefix: str = DEFAULT_TELEGRAM_THREAD_PREFIX) -> str:
    normalized = str(chat_id).strip()
    if normalized.startswith("-"):
        normalized = f"m{normalized[1:]}"
    return f"{prefix}-{normalized}"


def chat_id_for_thread_id(thread_id: str, *, prefix: str = DEFAULT_TELEGRAM_THREAD_PREFIX) -> int | None:
    marker = f"{prefix}-"
    if not thread_id.startswith(marker):
        return None
    raw = thread_id[len(marker) :].strip()
    if not raw:
        return None
    if raw.startswith("m") and raw[1:].isdigit():
        return -int(raw[1:])
    if raw.isdigit():
        return int(raw)
    return None


async def run_telegram_bridge(*, client: AgentClient, config: TelegramBotConfig) -> None:
    bridge = TelegramBotBridge(config=config, agent_client=client)
    await bridge.run_forever()

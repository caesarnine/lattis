from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
from pydantic_ai.ui.vercel_ai.request_types import (
    FileUIPart,
    SubmitMessage,
    TextUIPart,
    UIMessage,
    UIMessagePart,
)

from lattis.client import AgentClient

logger = logging.getLogger(__name__)

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
TELEGRAM_DEFAULT_MAX_MEDIA_BYTES = 20 * 1024 * 1024
DEFAULT_TELEGRAM_SESSION_ID = "telegram-bot"


@dataclass(frozen=True)
class TelegramBotConfig:
    token: str
    session_id: str = DEFAULT_TELEGRAM_SESSION_ID
    poll_timeout: int = 30
    max_media_bytes: int = TELEGRAM_DEFAULT_MAX_MEDIA_BYTES
    telegram_api_base: str = "https://api.telegram.org"

    @property
    def telegram_base_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/bot{self.token}"


class TelegramChannelAdapter:
    channel = "telegram"

    def __init__(
        self,
        *,
        token: str,
        telegram_api_base: str = "https://api.telegram.org",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.token = token
        self.telegram_api_base = telegram_api_base
        self._client = client or httpx.AsyncClient(
            base_url=f"{telegram_api_base.rstrip('/')}/bot{token}",
            timeout=httpx.Timeout(40.0, connect=10.0),
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send_text(self, *, external_conversation_id: str, text: str) -> None:
        chat_id = _parse_telegram_chat_id(external_conversation_id)
        for chunk in split_telegram_message(text):
            response = await self._client.post(
                "/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                detail = payload.get("description") if isinstance(payload, dict) else None
                raise RuntimeError(str(detail or "Telegram sendMessage failed."))


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


@dataclass(frozen=True)
class TelegramMediaRef:
    file_id: str
    media_type: str
    filename: str | None = None
    file_size: int | None = None


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
        self._chat_threads: dict[int, str] = {}
        self._offset: int | None = None

    async def close(self) -> None:
        if self._owns_telegram_client:
            await self._telegram_client.aclose()

    async def run_forever(self) -> None:
        logger.info(
            "starting telegram bridge session=%s",
            self.config.session_id,
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
        incoming_text = _as_non_empty_string(message.get("text"))
        if incoming_text is not None:
            incoming_text = incoming_text.strip() or None
        command = _normalize_command(incoming_text)

        if command is None and not _message_has_user_content(message):
            return

        lock = self._chat_locks.setdefault(chat_id, asyncio.Lock())
        async with lock:
            await self._handle_chat_message(chat_id, message=message, command=command)

    async def _handle_chat_message(
        self,
        chat_id: int,
        *,
        message: dict[str, object],
        command: str | None,
    ) -> None:
        thread_id = await self._resolve_thread_for_chat(chat_id, message=message)

        if command in {"/start", "/help"}:
            await self._send_message(
                chat_id,
                (
                    "Connected to Lattis.\n"
                    f"This chat is bound to thread '{thread_id}'.\n"
                    "Send text, images, audio, or video to chat with the active agent.\n"
                    "Use /clear to reset this thread."
                ),
            )
            return

        if command in {"/clear", "/reset"}:
            await self.agent_client.clear_thread(self.config.session_id, thread_id)
            await self._send_message(chat_id, "Cleared this thread.")
            return

        try:
            parts = await self._build_user_parts(message)
            if not parts:
                return
            await self._send_typing(chat_id)
            run_input = build_run_input(parts=parts, session_id=self.config.session_id, thread_id=thread_id)
            response_text = await collect_assistant_text(self.agent_client.run_stream(run_input))
            if not response_text:
                response_text = "(No assistant text returned.)"
            await self._send_message(chat_id, response_text)
        except Exception as exc:
            logger.exception("telegram run failed chat_id=%s thread_id=%s", chat_id, thread_id)
            await self._send_message(chat_id, f"Run error: {exc}")

    async def _build_user_parts(self, message: dict[str, object]) -> list[UIMessagePart]:
        parts: list[UIMessagePart] = []
        text = _as_non_empty_string(message.get("text"))
        caption = _as_non_empty_string(message.get("caption"))

        content_text = (text or "").strip() or (caption or "").strip()
        if content_text:
            parts.append(TextUIPart(text=content_text))

        media_refs = extract_telegram_media_refs(message)
        for item in media_refs:
            file_part = await self._download_file_part(item)
            parts.append(file_part)
        return parts

    async def _download_file_part(self, item: TelegramMediaRef) -> FileUIPart:
        if item.file_size is not None and item.file_size > self.config.max_media_bytes:
            raise RuntimeError(
                f"Attachment too large ({item.file_size} bytes). "
                f"Limit is {self.config.max_media_bytes} bytes."
            )

        payload = await self._telegram_request("getFile", {"file_id": item.file_id})
        result = payload.get("result")
        if not isinstance(result, dict):
            raise RuntimeError("Telegram getFile returned invalid result payload.")

        file_path = _as_non_empty_string(result.get("file_path"))
        if not file_path:
            raise RuntimeError("Telegram getFile response missing file_path.")

        file_url = f"{self.config.telegram_api_base.rstrip('/')}/file/bot{self.config.token}/{file_path}"
        response = await self._telegram_client.get(file_url)
        response.raise_for_status()
        blob = response.content
        if len(blob) > self.config.max_media_bytes:
            raise RuntimeError(
                f"Attachment too large after download ({len(blob)} bytes). "
                f"Limit is {self.config.max_media_bytes} bytes."
            )

        filename = item.filename or file_path.rsplit("/", 1)[-1]
        media_type = normalize_media_type(item.media_type, filename=filename)
        return FileUIPart(
            media_type=media_type,
            filename=filename or None,
            url=to_data_url(blob, media_type=media_type),
        )

    async def _resolve_thread_for_chat(self, chat_id: int, *, message: dict[str, object]) -> str:
        cached = self._chat_threads.get(chat_id)
        if cached:
            return cached

        sender = message.get("from")
        sender_id: str | None = None
        if isinstance(sender, dict):
            raw_sender_id = sender.get("id")
            if isinstance(raw_sender_id, int):
                sender_id = str(raw_sender_id)

        chat = message.get("chat")
        metadata: dict[str, object] | None = None
        if isinstance(chat, dict):
            metadata = {}
            chat_type = _as_non_empty_string(chat.get("type"))
            chat_title = _as_non_empty_string(chat.get("title"))
            chat_username = _as_non_empty_string(chat.get("username"))
            if chat_type:
                metadata["chat_type"] = chat_type
            if chat_title:
                metadata["chat_title"] = chat_title
            if chat_username:
                metadata["chat_username"] = chat_username
            if not metadata:
                metadata = None

        resolved = await self.agent_client.resolve_channel_thread(
            channel="telegram",
            session_id=self.config.session_id,
            external_conversation_id=str(chat_id),
            external_user_id=sender_id,
            metadata=metadata,
        )
        self._chat_threads[chat_id] = resolved.thread_id
        return resolved.thread_id

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


def _as_optional_positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    return None


def _normalize_command(text: str | None) -> str | None:
    if not text:
        return None
    first = text.strip().split(maxsplit=1)[0]
    if not first.startswith("/"):
        return None
    command = first.split("@", 1)[0].strip().lower()
    return command or None


def _message_has_user_content(message: dict[str, object]) -> bool:
    text = _as_non_empty_string(message.get("text"))
    caption = _as_non_empty_string(message.get("caption"))
    if text and text.strip():
        return True
    if caption and caption.strip():
        return True
    return bool(extract_telegram_media_refs(message))


def normalize_media_type(value: str, *, filename: str | None = None) -> str:
    media_type = value.strip().lower() or "application/octet-stream"
    if media_type == "application/octet-stream" and filename:
        guessed, _ = mimetypes.guess_type(filename)
        if guessed:
            return guessed
    return media_type


def to_data_url(data: bytes, *, media_type: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def extract_telegram_media_refs(message: dict[str, object]) -> list[TelegramMediaRef]:
    refs: list[TelegramMediaRef] = []

    photo = message.get("photo")
    if isinstance(photo, list):
        best: dict[str, object] | None = None
        best_size = -1
        for item in photo:
            if not isinstance(item, dict):
                continue
            file_id = _as_non_empty_string(item.get("file_id"))
            if not file_id:
                continue
            size = _as_optional_positive_int(item.get("file_size")) or 0
            if size >= best_size:
                best = item
                best_size = size
        if best is not None:
            file_id = _as_non_empty_string(best.get("file_id"))
            if file_id:
                refs.append(
                    TelegramMediaRef(
                        file_id=file_id,
                        media_type="image/jpeg",
                        file_size=_as_optional_positive_int(best.get("file_size")),
                    )
                )

    video = message.get("video")
    if isinstance(video, dict):
        file_id = _as_non_empty_string(video.get("file_id"))
        if file_id:
            refs.append(
                TelegramMediaRef(
                    file_id=file_id,
                    media_type=normalize_media_type(_as_non_empty_string(video.get("mime_type")) or "video/mp4"),
                    filename=_as_non_empty_string(video.get("file_name")),
                    file_size=_as_optional_positive_int(video.get("file_size")),
                )
            )

    video_note = message.get("video_note")
    if isinstance(video_note, dict):
        file_id = _as_non_empty_string(video_note.get("file_id"))
        if file_id:
            refs.append(
                TelegramMediaRef(
                    file_id=file_id,
                    media_type="video/mp4",
                    file_size=_as_optional_positive_int(video_note.get("file_size")),
                )
            )

    voice = message.get("voice")
    if isinstance(voice, dict):
        file_id = _as_non_empty_string(voice.get("file_id"))
        if file_id:
            refs.append(
                TelegramMediaRef(
                    file_id=file_id,
                    media_type=normalize_media_type(_as_non_empty_string(voice.get("mime_type")) or "audio/ogg"),
                    file_size=_as_optional_positive_int(voice.get("file_size")),
                )
            )

    audio = message.get("audio")
    if isinstance(audio, dict):
        file_id = _as_non_empty_string(audio.get("file_id"))
        if file_id:
            refs.append(
                TelegramMediaRef(
                    file_id=file_id,
                    media_type=normalize_media_type(_as_non_empty_string(audio.get("mime_type")) or "audio/mpeg"),
                    filename=_as_non_empty_string(audio.get("file_name")),
                    file_size=_as_optional_positive_int(audio.get("file_size")),
                )
            )

    document = message.get("document")
    if isinstance(document, dict):
        file_id = _as_non_empty_string(document.get("file_id"))
        if file_id:
            filename = _as_non_empty_string(document.get("file_name"))
            refs.append(
                TelegramMediaRef(
                    file_id=file_id,
                    media_type=normalize_media_type(
                        _as_non_empty_string(document.get("mime_type")) or "application/octet-stream",
                        filename=filename,
                    ),
                    filename=filename,
                    file_size=_as_optional_positive_int(document.get("file_size")),
                )
            )

    return refs


def build_run_input(
    *,
    text: str | None = None,
    parts: list[UIMessagePart] | None = None,
    session_id: str,
    thread_id: str,
) -> SubmitMessage:
    content_parts = list(parts or [])
    if text and text.strip():
        content_parts.insert(0, TextUIPart(text=text.strip()))
    if not content_parts:
        raise ValueError("At least one user message part is required.")

    return SubmitMessage(
        id=uuid4().hex,
        messages=[
            UIMessage(
                id=uuid4().hex,
                role="user",
                parts=content_parts,
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


def _parse_telegram_chat_id(value: str) -> int:
    normalized = value.strip()
    if normalized.startswith("-") and normalized[1:].isdigit():
        return -int(normalized[1:])
    if normalized.isdigit():
        return int(normalized)
    raise ValueError(f"Invalid Telegram conversation id '{value}'.")


async def run_telegram_bridge(*, client: AgentClient, config: TelegramBotConfig) -> None:
    bridge = TelegramBotBridge(config=config, agent_client=client)
    await bridge.run_forever()

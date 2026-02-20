from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage

from lattis.domain.schedules import (
    ScheduleRecord,
    cancel_schedule,
    claim_due_schedules,
    complete_schedule_run,
    fail_schedule_run,
    format_due_at,
)
from lattis.domain.threads import ThreadNotFoundError
from lattis.runtime.chat import create_chat_stream
from lattis.runtime.context import AppContext
from lattis.telegram import DEFAULT_TELEGRAM_THREAD_PREFIX, chat_id_for_thread_id, split_telegram_message

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerConfig:
    poll_interval_seconds: float = 2.0
    claim_limit: int = 10
    lease_seconds: int = 120
    retry_delay_seconds: int = 60
    run_once: bool = False
    telegram_bot_token: str | None = None
    telegram_thread_prefix: str = DEFAULT_TELEGRAM_THREAD_PREFIX


class _StreamTextCollector:
    def __init__(self) -> None:
        self._order: list[str] = []
        self._chunks: dict[str, list[str]] = {}

    def add(self, chunk: object) -> None:
        chunk_type = self._field(chunk, "type")
        if not isinstance(chunk_type, str):
            return
        if chunk_type == "error":
            detail = self._field(chunk, "error_text")
            if not isinstance(detail, str):
                detail = self._field(chunk, "errorText")
            message = detail.strip() if isinstance(detail, str) else "scheduler run error"
            raise RuntimeError(message)
        if chunk_type == "text-start":
            message_id = self._field(chunk, "id")
            if isinstance(message_id, str) and message_id:
                self._ensure(message_id)
            return
        if chunk_type == "text-delta":
            message_id = self._field(chunk, "id")
            delta = self._field(chunk, "delta")
            if isinstance(message_id, str) and message_id and isinstance(delta, str) and delta:
                self._ensure(message_id)
                self._chunks[message_id].append(delta)

    def render(self) -> str:
        parts: list[str] = []
        for message_id in self._order:
            content = "".join(self._chunks.get(message_id, []))
            if content.strip():
                parts.append(content.strip())
        return "\n\n".join(parts)

    def _ensure(self, message_id: str) -> None:
        if message_id in self._chunks:
            return
        self._chunks[message_id] = []
        self._order.append(message_id)

    @staticmethod
    def _field(chunk: object, name: str) -> object | None:
        if isinstance(chunk, dict):
            return chunk.get(name)
        return getattr(chunk, name, None)


@dataclass
class SchedulerWorker:
    ctx: AppContext
    config: SchedulerConfig
    _telegram_client: httpx.AsyncClient | None = field(default=None, init=False)

    async def close(self) -> None:
        if self._telegram_client is not None:
            await self._telegram_client.aclose()
            self._telegram_client = None

    async def run(self) -> None:
        logger.info(
            "scheduler start poll=%ss claim_limit=%s lease=%ss retry=%ss",
            self.config.poll_interval_seconds,
            self.config.claim_limit,
            self.config.lease_seconds,
            self.config.retry_delay_seconds,
        )
        try:
            while True:
                claimed = await self.run_once()
                if self.config.run_once:
                    return
                if claimed == 0:
                    await asyncio.sleep(max(0.1, self.config.poll_interval_seconds))
        finally:
            await self.close()

    async def run_once(self) -> int:
        due = claim_due_schedules(
            self.ctx.store,
            limit=self.config.claim_limit,
            lease_seconds=self.config.lease_seconds,
        )
        if not due:
            return 0
        for schedule in due:
            await self._process_schedule(schedule)
        return len(due)

    async def _process_schedule(self, schedule: ScheduleRecord) -> None:
        try:
            message = await self._run_schedule(schedule)
            await self._deliver_proactive_message(schedule, message)
            complete_schedule_run(self.ctx.store, schedule=schedule)
            logger.info(
                "schedule complete id=%s thread=%s next=%s",
                schedule.schedule_id,
                schedule.thread_id,
                "interval" if schedule.interval_seconds else "none",
            )
        except ThreadNotFoundError:
            logger.warning(
                "schedule thread missing; canceling schedule id=%s thread=%s",
                schedule.schedule_id,
                schedule.thread_id,
            )
            cancel_schedule(
                self.ctx.store,
                session_id=schedule.session_id,
                thread_id=schedule.thread_id,
                schedule_id=schedule.schedule_id,
            )
        except Exception as exc:
            logger.exception("schedule failed id=%s", schedule.schedule_id)
            fail_schedule_run(
                self.ctx.store,
                schedule=schedule,
                error=str(exc),
                retry_delay_seconds=self.config.retry_delay_seconds,
            )

    async def _run_schedule(self, schedule: ScheduleRecord) -> str:
        run_input = SubmitMessage(
            id=uuid4().hex,
            session_id=schedule.session_id,
            thread_id=schedule.thread_id,
            scheduler_trigger=True,
            messages=[
                UIMessage(
                    id=uuid4().hex,
                    role="user",
                    parts=[TextUIPart(text=self._build_trigger_prompt(schedule))],
                )
            ],
        )
        _, stream = create_chat_stream(self.ctx, run_input, accept="text/event-stream")
        collector = _StreamTextCollector()
        async for chunk in stream:
            collector.add(chunk)
        text = collector.render().strip()
        if text:
            return text
        return schedule.prompt

    async def _deliver_proactive_message(self, schedule: ScheduleRecord, message: str) -> None:
        chat_id = chat_id_for_thread_id(
            schedule.thread_id,
            prefix=self.config.telegram_thread_prefix,
        )
        if chat_id is None:
            return
        token = (self.config.telegram_bot_token or "").strip()
        if not token:
            raise RuntimeError(
                "Telegram token is required for proactive delivery to Telegram threads."
            )
        client = self._telegram_client
        if client is None:
            client = httpx.AsyncClient(
                base_url=f"https://api.telegram.org/bot{token}",
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
            self._telegram_client = client

        text = message.strip() or f"Reminder: {schedule.prompt}"
        for chunk in split_telegram_message(text):
            response = await client.post(
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

    @staticmethod
    def _build_trigger_prompt(schedule: ScheduleRecord) -> str:
        return (
            "Scheduled reminder trigger.\n"
            f"Schedule ID: {schedule.schedule_id}\n"
            f"Due (UTC): {format_due_at(schedule.due_at)}\n"
            f"Reminder request: {schedule.prompt}\n\n"
            "Please send the proactive reminder message to the user now."
        )


async def run_scheduler(ctx: AppContext, config: SchedulerConfig) -> None:
    worker = SchedulerWorker(ctx=ctx, config=config)
    await worker.run()

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import uuid4

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.ui.vercel_ai.request_types import SubmitMessage, TextUIPart, UIMessage

from lattis.channels import (
    ChannelAdapterNotConfiguredError,
    ChannelAdapterRegistry,
    build_default_channel_adapter_registry,
)
from lattis.domain.channels import list_thread_channel_bindings
from lattis.domain.messages import merge_messages
from lattis.domain.outbox import (
    NotificationOutboxRecord,
    claim_due_notifications,
    enqueue_notification,
    mark_notification_dead,
    mark_notification_sent,
    retry_notification,
)
from lattis.domain.schedules import (
    SCHEDULE_RUN_STATUS_DONE,
    SCHEDULE_RUN_STATUS_FAILED,
    ScheduleRecord,
    cancel_schedule,
    claim_due_schedules,
    complete_schedule_run,
    create_schedule_run,
    fail_schedule_run,
    finish_schedule_run,
    format_timestamp,
)
from lattis.domain.threads import ThreadNotFoundError, load_thread_messages
from lattis.runtime.chat import create_ephemeral_chat_stream
from lattis.runtime.context import AppContext
from lattis.schedule_tools import collect_scheduler_notifications

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerConfig:
    poll_interval_seconds: float = 2.0
    claim_limit: int = 10
    lease_seconds: int = 120
    retry_delay_seconds: int = 60
    run_once: bool = False
    telegram_bot_token: str | None = None

    outbox_claim_limit: int = 25
    outbox_lease_seconds: int = 120
    outbox_retry_delay_seconds: int = 60
    outbox_max_attempts: int = 5


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
    channel_adapters: ChannelAdapterRegistry | None = None

    def __post_init__(self) -> None:
        if self.channel_adapters is not None:
            return
        self.channel_adapters = build_default_channel_adapter_registry(
            telegram_bot_token=self.config.telegram_bot_token,
        )

    async def close(self) -> None:
        if self.channel_adapters is None:
            return
        await self.channel_adapters.close()

    async def run(self) -> None:
        logger.info(
            (
                "scheduler start poll=%ss claim_limit=%s lease=%ss retry=%ss "
                "outbox_claim=%s outbox_lease=%ss outbox_retry=%ss"
            ),
            self.config.poll_interval_seconds,
            self.config.claim_limit,
            self.config.lease_seconds,
            self.config.retry_delay_seconds,
            self.config.outbox_claim_limit,
            self.config.outbox_lease_seconds,
            self.config.outbox_retry_delay_seconds,
        )
        try:
            while True:
                processed = await self.run_once()
                if self.config.run_once:
                    return
                if processed == 0:
                    await asyncio.sleep(max(0.1, self.config.poll_interval_seconds))
        finally:
            await self.close()

    async def run_once(self) -> int:
        processed = 0
        due = claim_due_schedules(
            self.ctx.store,
            limit=self.config.claim_limit,
            lease_seconds=self.config.lease_seconds,
        )
        for schedule in due:
            await self._process_schedule(schedule)
            processed += 1

        processed += await self._dispatch_outbox_once()
        return processed

    async def _process_schedule(self, schedule: ScheduleRecord) -> None:
        trigger_prompt = self._build_trigger_prompt(schedule)
        run_record = create_schedule_run(
            self.ctx.store,
            schedule=schedule,
            trigger_prompt=trigger_prompt,
        )
        try:
            result_text, notifications = await self._run_schedule(schedule, trigger_prompt=trigger_prompt)
            notified_count = 0
            clean_notifications: list[str] = []
            for message in notifications:
                text = message.strip()
                if not text:
                    continue
                clean_notifications.append(text)
                self._append_assistant_notification(schedule, text)
                notified_count += 1

            queued_count = self._enqueue_notifications(
                schedule,
                run_id=run_record.run_id,
                notifications=clean_notifications,
            )

            complete_schedule_run(self.ctx.store, schedule=schedule)
            finish_schedule_run(
                self.ctx.store,
                run_id=run_record.run_id,
                status=SCHEDULE_RUN_STATUS_DONE,
                result_text=result_text or None,
                error=None,
                notified_count=notified_count,
            )
            logger.info(
                "schedule complete id=%s thread=%s notifications=%s queued=%s next=%s",
                schedule.schedule_id,
                schedule.thread_id,
                notified_count,
                queued_count,
                schedule.trigger_type,
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
            finish_schedule_run(
                self.ctx.store,
                run_id=run_record.run_id,
                status=SCHEDULE_RUN_STATUS_FAILED,
                result_text=None,
                error=f"Thread '{schedule.thread_id}' not found.",
                notified_count=0,
            )
        except Exception as exc:
            logger.exception("schedule failed id=%s", schedule.schedule_id)
            fail_schedule_run(
                self.ctx.store,
                schedule=schedule,
                error=str(exc),
                retry_delay_seconds=self.config.retry_delay_seconds,
            )
            finish_schedule_run(
                self.ctx.store,
                run_id=run_record.run_id,
                status=SCHEDULE_RUN_STATUS_FAILED,
                result_text=None,
                error=str(exc),
                notified_count=0,
            )

    def _enqueue_notifications(
        self,
        schedule: ScheduleRecord,
        *,
        run_id: str,
        notifications: list[str],
    ) -> int:
        if not notifications:
            return 0

        bindings = list_thread_channel_bindings(
            self.ctx.store,
            session_id=schedule.session_id,
            thread_id=schedule.thread_id,
        )
        if not bindings:
            return 0

        queued = 0
        for index, text in enumerate(notifications):
            for binding in bindings:
                dedupe_key = (
                    f"schedule:{schedule.schedule_id}:run:{run_id}:"
                    f"message:{index}:channel:{binding.channel}:conversation:{binding.external_conversation_id}"
                )
                enqueue_notification(
                    self.ctx.store,
                    session_id=schedule.session_id,
                    thread_id=schedule.thread_id,
                    schedule_id=schedule.schedule_id,
                    schedule_run_id=run_id,
                    channel=binding.channel,
                    external_conversation_id=binding.external_conversation_id,
                    text=text,
                    dedupe_key=dedupe_key,
                )
                queued += 1
        return queued

    async def _dispatch_outbox_once(self) -> int:
        due = claim_due_notifications(
            self.ctx.store,
            limit=self.config.outbox_claim_limit,
            lease_seconds=self.config.outbox_lease_seconds,
        )
        if not due:
            return 0

        for record in due:
            await self._deliver_outbox_record(record)
        return len(due)

    async def _deliver_outbox_record(self, record: NotificationOutboxRecord) -> None:
        text = record.text.strip()
        if not text:
            mark_notification_sent(self.ctx.store, outbox_id=record.outbox_id)
            return

        try:
            await self._deliver_channel_message(record, text=text)
        except Exception as exc:
            error = str(exc)
            if record.attempt_count >= self.config.outbox_max_attempts:
                mark_notification_dead(
                    self.ctx.store,
                    outbox_id=record.outbox_id,
                    error=error,
                )
                logger.error(
                    "outbox dead id=%s channel=%s conversation=%s error=%s",
                    record.outbox_id,
                    record.channel,
                    record.external_conversation_id,
                    error,
                )
            else:
                retry_notification(
                    self.ctx.store,
                    outbox_id=record.outbox_id,
                    error=error,
                    retry_delay_seconds=self.config.outbox_retry_delay_seconds,
                )
                logger.warning(
                    "outbox retry id=%s channel=%s conversation=%s attempt=%s error=%s",
                    record.outbox_id,
                    record.channel,
                    record.external_conversation_id,
                    record.attempt_count,
                    error,
                )
            return

        mark_notification_sent(self.ctx.store, outbox_id=record.outbox_id)
        logger.info(
            "outbox sent id=%s channel=%s conversation=%s",
            record.outbox_id,
            record.channel,
            record.external_conversation_id,
        )

    async def _deliver_channel_message(self, record: NotificationOutboxRecord, *, text: str) -> None:
        registry = self.channel_adapters
        if registry is None:
            raise RuntimeError("Channel adapter registry is not configured.")
        try:
            await registry.send_text(
                channel=record.channel,
                external_conversation_id=record.external_conversation_id,
                text=text,
            )
        except ChannelAdapterNotConfiguredError as exc:
            raise RuntimeError(str(exc)) from exc

    async def _run_schedule(
        self,
        schedule: ScheduleRecord,
        *,
        trigger_prompt: str,
    ) -> tuple[str, list[str]]:
        run_input = SubmitMessage(
            id=uuid4().hex,
            session_id=schedule.session_id,
            thread_id=schedule.thread_id,
            scheduler_trigger=True,
            schedule_id=schedule.schedule_id,
            messages=[
                UIMessage(
                    id=uuid4().hex,
                    role="user",
                    parts=[TextUIPart(text=trigger_prompt)],
                )
            ],
        )
        _, deps, stream = create_ephemeral_chat_stream(self.ctx, run_input, accept="text/event-stream")
        collector = _StreamTextCollector()
        async for chunk in stream:
            collector.add(chunk)
        return collector.render().strip(), collect_scheduler_notifications(deps)

    def _append_assistant_notification(self, schedule: ScheduleRecord, message: str) -> None:
        existing = list(
            load_thread_messages(
                self.ctx.store,
                session_id=schedule.session_id,
                thread_id=schedule.thread_id,
            )
        )
        assistant = ModelResponse(parts=[TextPart(content=message.strip())])
        updated = merge_messages(existing, [assistant])
        self.ctx.store.save_thread(
            schedule.session_id,
            schedule.thread_id,
            messages=updated,
        )

    @staticmethod
    def _build_trigger_prompt(schedule: ScheduleRecord) -> str:
        return (
            "Scheduled background task trigger.\n"
            f"Schedule: {schedule.name} ({schedule.schedule_id})\n"
            f"Next run (UTC): {format_timestamp(schedule.next_run_at)}\n"
            f"Trigger: {schedule.trigger_type}\n"
            f"Task request: {schedule.prompt}\n\n"
            "Run the task now. Use schedule_state_get and schedule_state_set for checkpointing.\n"
            "Only call notify_user when the user should receive an actual proactive message.\n"
            "If nothing should be sent, do not call notify_user."
        )


async def run_scheduler(ctx: AppContext, config: SchedulerConfig) -> None:
    worker = SchedulerWorker(ctx=ctx, config=config)
    await worker.run()

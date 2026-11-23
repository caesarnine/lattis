from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from pydantic import TypeAdapter

from lattis.protocol.schemas import (
    BusResyncRequiredEvent,
    LattisEvent,
    ResyncRequiredData,
)

LattisEventAdapter: TypeAdapter[LattisEvent] = TypeAdapter(LattisEvent)


@dataclass(eq=False)
class _Subscriber:
    queue: asyncio.Queue[LattisEvent | None]
    workspace_id: str | None = None
    thread_id: str | None = None
    overflowed: bool = False

    def matches(self, event: LattisEvent) -> bool:
        if self.workspace_id is not None and event.workspace_id != self.workspace_id:
            return False
        if self.thread_id is not None and event.thread_id != self.thread_id:
            return False
        return True


class EventBus:
    """In-memory pub/sub event bus with monotonic seq numbers and ring-buffer replay."""

    def __init__(self, *, max_buffer: int = 2000, subscriber_queue_size: int = 512) -> None:
        self._seq = 0
        self._buffer: deque[LattisEvent] = deque(maxlen=max_buffer)
        self._subscribers: set[_Subscriber] = set()
        self._subscriber_queue_size = subscriber_queue_size
        self._closed = False

    @property
    def latest_seq(self) -> int:
        return self._seq

    @property
    def earliest_seq(self) -> int | None:
        return self._buffer[0].seq if self._buffer else None

    def publish(
        self,
        event_cls: type[Any],
        *,
        data: Any,
        workspace_id: str | None = None,
        thread_id: str | None = None,
        run_id: str | None = None,
    ) -> LattisEvent:
        self._seq += 1
        event: LattisEvent = event_cls(
            seq=self._seq,
            timestamp=time.time(),
            workspace_id=workspace_id,
            thread_id=thread_id,
            run_id=run_id,
            data=data,
        )
        self._buffer.append(event)
        for sub in list(self._subscribers):
            if not sub.matches(event):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.overflowed = True
        return event

    def close(self) -> None:
        self._closed = True
        for sub in list(self._subscribers):
            try:
                sub.queue.put_nowait(None)
            except asyncio.QueueFull:
                # Drain one item to make room for sentinel
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait(None)
                except asyncio.QueueEmpty:
                    pass

    async def subscribe(
        self,
        *,
        workspace_id: str | None = None,
        thread_id: str | None = None,
        after_seq: int | None = None,
    ) -> AsyncIterator[LattisEvent]:
        sub = _Subscriber(
            queue=asyncio.Queue(maxsize=self._subscriber_queue_size),
            workspace_id=workspace_id,
            thread_id=thread_id,
        )
        self._subscribers.add(sub)
        try:
            # Replay buffered events if requested
            replayed_up_to = 0
            if after_seq is not None and after_seq >= 0:
                earliest = self.earliest_seq
                if earliest is not None and after_seq < earliest - 1:
                    yield BusResyncRequiredEvent(
                        seq=self._seq,
                        timestamp=time.time(),
                        workspace_id=workspace_id,
                        thread_id=thread_id,
                        data=ResyncRequiredData(
                            reason="Requested sequence predates ring buffer.",
                            earliest_seq=earliest,
                            latest_seq=self._seq,
                        ),
                    )
                    replayed_up_to = self._seq
                else:
                    snapshot = list(self._buffer)
                    for buffered in snapshot:
                        if buffered.seq <= after_seq:
                            continue
                        if not sub.matches(buffered):
                            continue
                        replayed_up_to = buffered.seq
                        yield buffered

            while not self._closed:
                event = await sub.queue.get()
                if event is None:
                    break
                if sub.overflowed:
                    sub.overflowed = False
                    # Drain stale queued items and ask client to resync
                    while not sub.queue.empty():
                        try:
                            item = sub.queue.get_nowait()
                            if item is None:
                                return
                        except asyncio.QueueEmpty:
                            break
                    yield BusResyncRequiredEvent(
                        seq=self._seq,
                        timestamp=time.time(),
                        workspace_id=workspace_id,
                        thread_id=thread_id,
                        data=ResyncRequiredData(
                            reason="Subscriber lagged behind event stream.",
                            earliest_seq=self.earliest_seq,
                            latest_seq=self._seq,
                        ),
                    )
                    replayed_up_to = self._seq
                    continue
                if event.seq <= replayed_up_to:
                    continue
                yield event
        finally:
            self._subscribers.discard(sub)


def format_sse_event(event: LattisEvent) -> str:
    payload = event.model_dump_json()
    return f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n"

from __future__ import annotations

import asyncio

from lattis.protocol.schemas import (
    BusResyncRequiredEvent,
    ThreadClearedEvent,
    ThreadIdData,
)
from lattis.runtime.events import EventBus


def test_event_bus_filters_and_replay() -> None:
    async def _run() -> None:
        bus = EventBus(max_buffer=5)
        e1 = bus.publish(ThreadClearedEvent, data=ThreadIdData(thread_id="t1"), workspace_id="w1", thread_id="t1")
        e2 = bus.publish(ThreadClearedEvent, data=ThreadIdData(thread_id="t2"), workspace_id="w2", thread_id="t2")
        e3 = bus.publish(ThreadClearedEvent, data=ThreadIdData(thread_id="t1"), workspace_id="w1", thread_id="t1")
        assert [e1.seq, e2.seq, e3.seq] == [1, 2, 3]

        received = []

        async def consume() -> None:
            async for ev in bus.subscribe(workspace_id="w1", after_seq=1):
                received.append(ev)
                if len(received) == 2:
                    break

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.01)
        bus.publish(ThreadClearedEvent, data=ThreadIdData(thread_id="t1"), workspace_id="w1", thread_id="t1")
        await asyncio.wait_for(task, timeout=2.0)

        assert [ev.seq for ev in received] == [3, 4]

    asyncio.run(_run())


def test_event_bus_ring_buffer_overflow_triggers_resync() -> None:
    async def _run() -> None:
        bus = EventBus(max_buffer=3)
        for i in range(6):
            bus.publish(ThreadClearedEvent, data=ThreadIdData(thread_id=f"t{i}"), workspace_id="w1", thread_id=f"t{i}")

        gen = bus.subscribe(after_seq=1)
        first = await gen.__anext__()
        await gen.aclose()

        assert isinstance(first, BusResyncRequiredEvent)
        assert first.data.earliest_seq == 4
        assert first.data.latest_seq == 6

    asyncio.run(_run())

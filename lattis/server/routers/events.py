from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from lattis.runtime.context import AppContext
from lattis.runtime.events import format_sse_event
from lattis.server.deps import get_ctx, require_auth

router = APIRouter(dependencies=[Depends(require_auth)])

_KEEPALIVE_SECONDS = 15.0


def _parse_after_seq(after_seq: int | None, last_event_id: str | None) -> int | None:
    if after_seq is not None:
        return after_seq
    if last_event_id:
        try:
            return int(last_event_id.strip())
        except ValueError:
            return None
    return None


@router.get("/events")
async def api_events(
    request: Request,
    workspace_id: str | None = Query(default=None),
    thread_id: str | None = Query(default=None),
    after_seq: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ctx: AppContext = Depends(get_ctx),
) -> StreamingResponse:
    resolved_after = _parse_after_seq(after_seq, last_event_id)

    async def event_stream() -> AsyncIterator[str]:
        yield ": connected\n\n"
        gen = ctx.bus.subscribe(
            workspace_id=workspace_id,
            thread_id=thread_id,
            after_seq=resolved_after,
        )
        iterator = gen.__aiter__()
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(iterator.__anext__(), timeout=_KEEPALIVE_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                except StopAsyncIteration:
                    break
                yield format_sse_event(event)
        finally:
            await gen.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

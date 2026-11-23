from __future__ import annotations

import json
from collections.abc import AsyncIterator

from lattis.protocol.schemas import LattisEvent
from lattis.runtime.events import LattisEventAdapter


async def iter_sse_events(lines: AsyncIterator[str]) -> AsyncIterator[LattisEvent]:
    """Parse Lattis Server-Sent Events lines into validated LattisEvent objects."""
    async for line in lines:
        if not line:
            continue
        if line.startswith(":"):
            continue
        if not line.startswith("data:"):
            continue
        payload = line[5:].lstrip()
        if not payload or payload == "[DONE]":
            continue
        try:
            raw = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        try:
            yield LattisEventAdapter.validate_python(raw)
        except Exception:
            continue

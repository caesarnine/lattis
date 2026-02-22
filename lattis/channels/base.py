from __future__ import annotations

from typing import Protocol


class ChannelAdapter(Protocol):
    channel: str

    async def send_text(self, *, external_conversation_id: str, text: str) -> None: ...

    async def close(self) -> None: ...

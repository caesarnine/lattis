from __future__ import annotations

import asyncio
from pathlib import Path

from lattis.client.inprocess import create_inprocess_client


def test_channel_thread_resolution_endpoint(tmp_path: Path) -> None:
    async def run() -> None:
        client, _server = create_inprocess_client(project_root=tmp_path)
        try:
            first = await client.resolve_channel_thread(
                channel="telegram",
                session_id="s1",
                external_conversation_id="12345",
            )
            second = await client.resolve_channel_thread(
                channel="telegram",
                session_id="s1",
                external_conversation_id="12345",
            )
        finally:
            await client.close()

        assert first.created is True
        assert second.created is False
        assert first.thread_id == second.thread_id

    asyncio.run(run())

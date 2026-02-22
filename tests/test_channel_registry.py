from __future__ import annotations

import asyncio

import pytest

from lattis.channels import (
    ChannelAdapterNotConfiguredError,
    ChannelAdapterRegistry,
    build_default_channel_adapter_registry,
)


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def send_text(self, *, external_conversation_id: str, text: str) -> None:
        self.calls.append((external_conversation_id, text))

    async def close(self) -> None:
        self.closed = True


def test_channel_adapter_registry_register_instance_and_send() -> None:
    registry = ChannelAdapterRegistry()
    adapter = _FakeAdapter()
    registry.register_instance(channel="TeLeGrAm", adapter=adapter)

    asyncio.run(
        registry.send_text(
            channel="telegram",
            external_conversation_id="123",
            text="hello",
        )
    )
    assert adapter.calls == [("123", "hello")]


def test_channel_adapter_registry_register_factory_lazily() -> None:
    registry = ChannelAdapterRegistry()
    created: list[_FakeAdapter] = []

    def factory() -> _FakeAdapter:
        adapter = _FakeAdapter()
        created.append(adapter)
        return adapter

    registry.register_factory(channel="telegram", factory=factory)

    asyncio.run(
        registry.send_text(
            channel="telegram",
            external_conversation_id="1",
            text="first",
        )
    )
    asyncio.run(
        registry.send_text(
            channel="telegram",
            external_conversation_id="2",
            text="second",
        )
    )

    assert len(created) == 1
    assert created[0].calls == [("1", "first"), ("2", "second")]

    asyncio.run(registry.close())
    assert created[0].closed is True


def test_channel_adapter_registry_missing_channel_raises() -> None:
    registry = ChannelAdapterRegistry()
    with pytest.raises(ChannelAdapterNotConfiguredError):
        asyncio.run(
            registry.send_text(
                channel="slack",
                external_conversation_id="abc",
                text="hello",
            )
        )


def test_build_default_channel_adapter_registry_without_token() -> None:
    registry = build_default_channel_adapter_registry(telegram_bot_token=None)
    with pytest.raises(ChannelAdapterNotConfiguredError):
        asyncio.run(
            registry.send_text(
                channel="telegram",
                external_conversation_id="123",
                text="hello",
            )
        )

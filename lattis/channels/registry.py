from __future__ import annotations

import logging
from collections.abc import Callable

from lattis.channels.base import ChannelAdapter

logger = logging.getLogger(__name__)

ChannelAdapterFactory = Callable[[], ChannelAdapter]


class ChannelAdapterNotConfiguredError(LookupError):
    pass


class ChannelAdapterRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ChannelAdapterFactory] = {}
        self._instances: dict[str, ChannelAdapter] = {}

    def register_factory(self, *, channel: str, factory: ChannelAdapterFactory) -> None:
        normalized = _normalize_channel(channel)
        self._factories[normalized] = factory
        self._instances.pop(normalized, None)

    def register_instance(self, *, channel: str, adapter: ChannelAdapter) -> None:
        normalized = _normalize_channel(channel)
        self._instances[normalized] = adapter

    async def send_text(
        self,
        *,
        channel: str,
        external_conversation_id: str,
        text: str,
    ) -> None:
        adapter = self._resolve_adapter(channel)
        await adapter.send_text(
            external_conversation_id=external_conversation_id,
            text=text,
        )

    async def close(self) -> None:
        adapters = list(self._instances.items())
        self._instances.clear()
        for channel, adapter in adapters:
            try:
                await adapter.close()
            except Exception as exc:  # pragma: no cover - defensive cleanup
                logger.warning("Failed to close channel adapter '%s': %s", channel, exc)

    def _resolve_adapter(self, channel: str) -> ChannelAdapter:
        normalized = _normalize_channel(channel)

        existing = self._instances.get(normalized)
        if existing is not None:
            return existing

        factory = self._factories.get(normalized)
        if factory is None:
            raise ChannelAdapterNotConfiguredError(
                f"No delivery adapter configured for channel '{channel}'."
            )

        adapter = factory()
        self._instances[normalized] = adapter
        return adapter


def build_default_channel_adapter_registry(*, telegram_bot_token: str | None) -> ChannelAdapterRegistry:
    registry = ChannelAdapterRegistry()

    token = (telegram_bot_token or "").strip()
    if token:
        from lattis.channels.telegram import TelegramChannelAdapter

        registry.register_factory(
            channel="telegram",
            factory=lambda: TelegramChannelAdapter(token=token),
        )

    return registry


def _normalize_channel(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ValueError("channel cannot be empty")
    return normalized

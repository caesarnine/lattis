from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from lattis.domain.sessions import SessionStore, generate_thread_id
from lattis.domain.threads import create_thread


class ChannelBindingValidationError(ValueError):
    pass


class ChannelBindingConflictError(ValueError):
    pass


@dataclass(frozen=True)
class ChannelBindingRecord:
    binding_id: str
    session_id: str
    thread_id: str
    channel: str
    external_conversation_id: str
    external_user_id: str | None
    metadata_json: dict[str, Any] | None
    created_at: float
    updated_at: float


def new_channel_binding_id() -> str:
    return f"bind-{uuid.uuid4().hex[:12]}"


def normalize_channel(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise ChannelBindingValidationError("channel cannot be empty.")
    return normalized


def normalize_external_conversation_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ChannelBindingValidationError("external conversation id cannot be empty.")
    return normalized


def list_thread_channel_bindings(
    store: SessionStore,
    *,
    session_id: str,
    thread_id: str,
) -> list[ChannelBindingRecord]:
    return store.list_thread_channel_bindings(
        session_id=session_id,
        thread_id=thread_id,
    )


def resolve_channel_thread_binding(
    store: SessionStore,
    *,
    session_id: str,
    channel: str,
    external_conversation_id: str,
    external_user_id: str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> tuple[ChannelBindingRecord, bool]:
    normalized_channel = normalize_channel(channel)
    normalized_external_id = normalize_external_conversation_id(external_conversation_id)

    existing = store.get_channel_binding_record(
        channel=normalized_channel,
        external_conversation_id=normalized_external_id,
    )
    now = time.time()

    if existing is not None and store.thread_exists(existing.session_id, existing.thread_id):
        if existing.session_id != session_id:
            raise ChannelBindingConflictError(
                "Channel conversation is already bound to a different session."
            )
        updated = store.upsert_channel_binding_record(
            binding_id=existing.binding_id,
            session_id=existing.session_id,
            thread_id=existing.thread_id,
            channel=existing.channel,
            external_conversation_id=existing.external_conversation_id,
            external_user_id=external_user_id,
            metadata_json=metadata_json,
            updated_at=now,
        )
        return updated, False

    thread_id = generate_thread_id(prefix=_thread_prefix_for_channel(normalized_channel))
    create_thread(store, session_id=session_id, thread_id=thread_id)

    created = store.upsert_channel_binding_record(
        binding_id=new_channel_binding_id(),
        session_id=session_id,
        thread_id=thread_id,
        channel=normalized_channel,
        external_conversation_id=normalized_external_id,
        external_user_id=external_user_id,
        metadata_json=metadata_json,
        updated_at=now,
    )
    return created, True


def _thread_prefix_for_channel(channel: str) -> str:
    chars = [ch for ch in channel if ch.isalnum()]
    prefix = "".join(chars)[:4]
    return prefix or "thread"

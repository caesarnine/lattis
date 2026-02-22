from __future__ import annotations

from lattis.domain.channels import resolve_channel_thread_binding
from lattis.protocol.schemas import ChannelThreadResolveRequest, ChannelThreadResolveResponse
from lattis.runtime.context import AppContext


def resolve_channel_thread(
    ctx: AppContext,
    *,
    channel: str,
    payload: ChannelThreadResolveRequest,
) -> ChannelThreadResolveResponse:
    binding, created = resolve_channel_thread_binding(
        ctx.store,
        session_id=payload.session_id,
        channel=channel,
        external_conversation_id=payload.external_conversation_id,
        external_user_id=payload.external_user_id,
        metadata_json=payload.metadata,
    )
    return ChannelThreadResolveResponse(
        session_id=binding.session_id,
        thread_id=binding.thread_id,
        channel=binding.channel,
        external_conversation_id=binding.external_conversation_id,
        created=created,
    )

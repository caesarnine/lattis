from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from lattis.domain.channels import ChannelBindingConflictError, ChannelBindingValidationError
from lattis.protocol.schemas import ChannelThreadResolveRequest, ChannelThreadResolveResponse
from lattis.runtime.channels import resolve_channel_thread
from lattis.runtime.context import AppContext
from lattis.server.deps import get_ctx

router = APIRouter()


@router.post(
    "/channels/{channel}/threads/resolve",
    response_model=ChannelThreadResolveResponse,
)
async def api_resolve_channel_thread(
    channel: str,
    payload: ChannelThreadResolveRequest,
    ctx: AppContext = Depends(get_ctx),
) -> ChannelThreadResolveResponse:
    try:
        return resolve_channel_thread(ctx, channel=channel, payload=payload)
    except ChannelBindingValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ChannelBindingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

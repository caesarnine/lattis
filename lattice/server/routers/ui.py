from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic_ai.exceptions import UserError

from lattice.domain.threads import ThreadNotFoundError
from lattice.runtime.chat import ChatRequestError, create_chat_stream, parse_run_input
from lattice.runtime.context import AppContext
from lattice.server.deps import get_ctx

router = APIRouter()


@router.post("/ui/chat")
async def ui_chat(request: Request, ctx: AppContext = Depends(get_ctx)):
    body = await request.body()
    try:
        run_input = parse_run_input(body)
        adapter, stream = create_chat_stream(
            ctx,
            run_input,
            accept=request.headers.get("accept"),
        )
    except ChatRequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ThreadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return adapter.streaming_response(stream)

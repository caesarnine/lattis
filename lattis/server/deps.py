from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, Query, Request

from lattis.runtime.context import AppContext


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def require_auth(
    request: Request,
    token: str | None = Query(default=None),
    ctx: AppContext = Depends(get_ctx),
) -> None:
    expected = ctx.auth_token
    if not expected:
        return

    provided: str | None = None
    auth_header = request.headers.get("authorization")
    if auth_header:
        scheme, _, value = auth_header.partition(" ")
        if scheme.lower() == "bearer" and value.strip():
            provided = value.strip()

    if provided is None and token:
        provided = token.strip()

    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

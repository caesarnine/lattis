from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx
from fastapi import FastAPI

from lattis.agents.registry import AgentRegistry, load_registry
from lattis.client.api import AgentClient
from lattis.runtime.context import AppContext
from lattis.server.app import create_app
from lattis.settings.storage import DaemonConfig, load_daemon_config

_UNSET = object()


@dataclass(frozen=True)
class InProcessDaemon:
    app: FastAPI
    ctx: AppContext
    config: DaemonConfig
    registry: AgentRegistry
    auth_token: str | None

    async def aclose(self) -> None:
        await self.ctx.run_manager.shutdown()
        self.ctx.bus.close()


def create_inprocess_client(
    *,
    home_dir: Path,
    registry: AgentRegistry | None = None,
    agent_specs: Iterable[str] | None = None,
    default_agent: str | None = None,
    auth_token: str | None | object = _UNSET,
    auth_disabled: bool = False,
    cors_origins: tuple[str, ...] = (),
) -> tuple[AgentClient, InProcessDaemon]:
    config = load_daemon_config(
        home_dir=home_dir,
        cors_origins=cors_origins,
        auth_disabled=auth_disabled,
    )
    resolved_registry = registry or load_registry(plugin_specs=agent_specs, default_spec=default_agent)
    app_kwargs: dict[str, object] = {"registry": resolved_registry}
    if auth_token is not _UNSET:
        app_kwargs["auth_token"] = auth_token
    app = create_app(config, **app_kwargs)  # type: ignore[arg-type]
    ctx: AppContext = app.state.ctx
    transport = httpx.ASGITransport(app=app)
    base_url = "http://lattis.inprocess"
    http_client = httpx.AsyncClient(base_url=base_url, transport=transport)
    client = AgentClient(base_url, token=ctx.auth_token, client=http_client)
    daemon = InProcessDaemon(
        app=app,
        ctx=ctx,
        config=config,
        registry=resolved_registry,
        auth_token=ctx.auth_token,
    )
    return client, daemon

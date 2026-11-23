from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from lattis.agents.registry import AgentRegistry, load_registry
from lattis.protocol.schemas import EventSchemaEnvelope
from lattis.runtime.context import AppContext
from lattis.runtime.events import EventBus
from lattis.runtime.runs import RunManager
from lattis.server.routers import agents, events, meta, plugins, runs, threads, workspace_fs, workspaces
from lattis.settings.storage import (
    DaemonConfig,
    load_daemon_config,
    load_or_create_auth_token,
)
from lattis.storage.sqlite import SQLiteDaemonStore
from lattis.web import get_static_dir

_UNSET = object()


def create_app(
    config: DaemonConfig | None = None,
    *,
    registry: AgentRegistry | None = None,
    auth_token: str | None | object = _UNSET,
) -> FastAPI:
    resolved_config = config or load_daemon_config()
    resolved_registry = registry or load_registry()
    resolved_token = (
        load_or_create_auth_token(resolved_config)
        if auth_token is _UNSET
        else auth_token  # type: ignore[assignment]
    )

    store = SQLiteDaemonStore(resolved_config.db_path)
    store.ensure_global_workspace(str(resolved_config.global_workspace_dir))
    store.recover_interrupted_runs()

    bus = EventBus()
    run_manager = RunManager(
        config=resolved_config,
        store=store,
        registry=resolved_registry,
        bus=bus,
    )
    ctx = AppContext(
        config=resolved_config,
        store=store,
        registry=resolved_registry,
        bus=bus,
        run_manager=run_manager,
        auth_token=resolved_token,  # type: ignore[arg-type]
        cors_origins=resolved_config.cors_origins,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        store.ensure_global_workspace(str(resolved_config.global_workspace_dir))
        store.recover_interrupted_runs()
        try:
            yield
        finally:
            await run_manager.shutdown()
            bus.close()

    app = FastAPI(title="Lattis Daemon API", version=meta.get_lattis_version(), lifespan=lifespan)
    app.state.ctx = ctx

    if resolved_config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_config.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(meta.router)
    app.include_router(agents.router)
    app.include_router(workspaces.router)
    app.include_router(workspace_fs.router)
    app.include_router(threads.router)
    app.include_router(runs.router)
    app.include_router(plugins.router)
    app.include_router(events.router)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        # Export the complete LattisEvent discriminated union into OpenAPI components
        envelope_schema = EventSchemaEnvelope.model_json_schema(ref_template="#/components/schemas/{model}")
        defs = envelope_schema.pop("$defs", {})
        components = schema.setdefault("components", {})
        schemas = components.setdefault("schemas", {})
        for name, definition in defs.items():
            schemas.setdefault(name, definition)
        schemas["EventSchemaEnvelope"] = envelope_schema
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    static_dir = get_static_dir()
    if static_dir.exists() and (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app

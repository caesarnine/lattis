from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from lattice.agents.registry import AgentRegistry, load_registry
from lattice.settings.storage import StorageConfig, load_storage_config
from lattice.storage.sqlite import SQLiteSessionStore
from lattice.app.context import AppContext
from lattice.server.routers import agents, meta, models, threads, ui
from lattice.web import get_static_dir


def create_app(
    config: StorageConfig | None = None,
    *,
    registry: AgentRegistry | None = None,
) -> FastAPI:
    config = config or load_storage_config()
    registry = registry or load_registry()
    store = SQLiteSessionStore(config.db_path)
    ctx = AppContext(
        config=config,
        store=store,
        registry=registry,
    )

    app = FastAPI(title="Lattice API")
    app.state.ctx = ctx

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(meta.router)
    app.include_router(agents.router)
    app.include_router(models.router)
    app.include_router(threads.router)
    app.include_router(ui.router)

    # Mount static files for web UI (must be last to act as SPA catch-all)
    static_dir = get_static_dir()
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")

    return app

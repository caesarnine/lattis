from __future__ import annotations

from lattice.app.context import AppContext
from lattice.app.thread_state import build_thread_state
from lattice.domain.threads import ThreadAlreadyExistsError, create_thread, list_threads
from lattice.protocol.schemas import SessionBootstrapResponse
from lattice.settings.storage import load_or_create_session_id


def bootstrap_session(ctx: AppContext, thread_id: str | None = None) -> SessionBootstrapResponse:
    session_id = load_or_create_session_id(ctx.config.session_id_path)
    threads = list_threads(ctx.store, session_id)

    requested = (thread_id or "").strip()
    if requested:
        selected_thread = requested
    elif threads:
        selected_thread = threads[0]
    else:
        selected_thread = "default"

    if selected_thread not in threads:
        try:
            create_thread(ctx.store, session_id=session_id, thread_id=selected_thread)
        except ThreadAlreadyExistsError:
            pass
        threads = list_threads(ctx.store, session_id)

    state = build_thread_state(ctx, session_id=session_id, thread_id=selected_thread)
    return SessionBootstrapResponse(
        session_id=session_id,
        thread_id=selected_thread,
        threads=threads,
        agent=state.agent,
        model=state.model,
        messages=state.messages,
    )

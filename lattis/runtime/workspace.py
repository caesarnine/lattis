from __future__ import annotations

import hashlib
import re
from pathlib import Path

_SAFE_SESSION_CHARS = re.compile(r"[^a-zA-Z0-9._-]+")


def session_workspace_path(workspace_base: Path, session_id: str) -> Path:
    """Return a stable per-session workspace directory under the shared workspace base."""
    raw = (session_id or "").strip()
    base = _SAFE_SESSION_CHARS.sub("-", raw).strip("-").lower() or "session"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8] if raw else "unknown"
    base = base[:48].rstrip("-") or "session"
    return workspace_base / "sessions" / f"{base}-{digest}"


def workspace_dir_for_session(
    *,
    workspace_base: Path,
    session_id: str,
    default_session_id: str,
) -> Path:
    """Resolve the filesystem workspace dir for a session.

    The default session uses the workspace base dir directly for backwards compatibility.
    Other sessions get a per-session subdirectory under `workspace_base/sessions/`.
    """
    if session_id.strip() == default_session_id.strip():
        return workspace_base
    return session_workspace_path(workspace_base, session_id)


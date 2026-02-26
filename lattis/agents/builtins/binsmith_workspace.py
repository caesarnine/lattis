from __future__ import annotations

import hashlib
import re
from pathlib import Path


_SAFE_THREAD_CHARS = re.compile(r"[^a-zA-Z0-9._-]+")


def thread_workspace_path(root: Path, thread_id: str) -> Path:
    """Return the per-thread workspace path under the shared workspace root."""
    raw = (thread_id or "").strip()
    base = _SAFE_THREAD_CHARS.sub("-", raw).strip("-").lower() or "thread"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8] if raw else "unknown"
    base = base[:48].rstrip("-") or "thread"
    return root / "threads" / f"{base}-{digest}"


def ensure_workspace(path: Path, *, project_root: Path | None = None) -> Path:
    """Ensure the Binsmith per-thread workspace directory structure exists."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "bin").mkdir(exist_ok=True)
    (path / "data").mkdir(exist_ok=True)
    (path / "tmp").mkdir(exist_ok=True)

    if project_root is not None:
        link = path / "project"
        try:
            if link.is_symlink():
                resolved = link.resolve(strict=False)
                if resolved != project_root.resolve(strict=False):
                    link.unlink(missing_ok=True)
            elif link.exists():
                # Leave pre-existing non-symlink content alone.
                return path
            if not link.exists():
                link.symlink_to(project_root)
        except OSError:
            pass

    return path

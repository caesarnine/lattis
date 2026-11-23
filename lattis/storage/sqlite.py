from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence

from pydantic_ai.messages import ModelMessage

from lattis.domain.errors import (
    RunNotFoundError,
    ThreadAlreadyExistsError,
    ThreadNotFoundError,
    WorkspaceNotFoundError,
    WorkspaceProtectedError,
)
from lattis.domain.messages import dump_messages, load_messages
from lattis.domain.models import (
    GLOBAL_WORKSPACE_ID,
    DaemonStore,
    ItemKind,
    ItemRecord,
    ItemStatus,
    RunRecord,
    RunStatus,
    ThreadRecord,
    ThreadStatus,
    WorkspaceKind,
    WorkspaceRecord,
    generate_item_id,
    generate_thread_id,
    generate_workspace_id,
)

SCHEMA_VERSION = 1
_UNSET = object()


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def _load_json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


class SQLiteDaemonStore(DaemonStore):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id          TEXT PRIMARY KEY,
                    name        TEXT NOT NULL,
                    root_path   TEXT NOT NULL UNIQUE,
                    kind        TEXT NOT NULL,
                    settings    TEXT NOT NULL DEFAULT '{}',
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    id             TEXT PRIMARY KEY,
                    workspace_id   TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    title          TEXT NOT NULL DEFAULT '',
                    agent_id       TEXT,
                    model          TEXT,
                    status         TEXT NOT NULL DEFAULT 'idle',
                    settings       TEXT NOT NULL DEFAULT '{}',
                    model_messages BLOB,
                    created_at     REAL NOT NULL,
                    updated_at     REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_threads_workspace_updated
                ON threads(workspace_id, updated_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id           TEXT PRIMARY KEY,
                    thread_id    TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    agent_id     TEXT NOT NULL,
                    model        TEXT NOT NULL,
                    status       TEXT NOT NULL,
                    usage        TEXT,
                    error        TEXT,
                    started_at   REAL NOT NULL,
                    ended_at     REAL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runs_thread_started
                ON runs(thread_id, started_at DESC)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id          TEXT PRIMARY KEY,
                    thread_id   TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    run_id      TEXT REFERENCES runs(id) ON DELETE SET NULL,
                    seq         INTEGER NOT NULL,
                    kind        TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL,
                    UNIQUE(thread_id, seq)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_items_thread_seq
                ON items(thread_id, seq ASC)
                """
            )
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # ------------------------------------------------------------------
    # Row mappers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_workspace(row: sqlite3.Row) -> WorkspaceRecord:
        return WorkspaceRecord(
            id=row["id"],
            name=row["name"],
            root_path=row["root_path"],
            kind=row["kind"],
            settings=_load_json_dict(row["settings"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _row_to_thread(row: sqlite3.Row) -> ThreadRecord:
        return ThreadRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            title=row["title"] or "",
            agent_id=row["agent_id"],
            model=row["model"],
            status=row["status"],
            settings=_load_json_dict(row["settings"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        usage = _load_json_dict(row["usage"]) if row["usage"] else None
        return RunRecord(
            id=row["id"],
            thread_id=row["thread_id"],
            workspace_id=row["workspace_id"],
            agent_id=row["agent_id"],
            model=row["model"],
            status=row["status"],
            usage=usage,
            error=row["error"],
            started_at=float(row["started_at"]),
            ended_at=float(row["ended_at"]) if row["ended_at"] is not None else None,
        )

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> ItemRecord:
        return ItemRecord(
            id=row["id"],
            thread_id=row["thread_id"],
            run_id=row["run_id"],
            seq=int(row["seq"]),
            kind=row["kind"],
            status=row["status"],
            payload=_load_json_dict(row["payload"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    # ------------------------------------------------------------------
    # Workspaces
    # ------------------------------------------------------------------

    def ensure_global_workspace(self, root_path: str) -> WorkspaceRecord:
        normalized = _normalize_path(root_path)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id = ?",
                (GLOBAL_WORKSPACE_ID,),
            ).fetchone()
            if row is not None:
                return self._row_to_workspace(row)
            conn.execute(
                """
                INSERT INTO workspaces (id, name, root_path, kind, settings, created_at, updated_at)
                VALUES (?, ?, ?, 'global', '{}', ?, ?)
                """,
                (GLOBAL_WORKSPACE_ID, "Global", normalized, now, now),
            )
            created = conn.execute(
                "SELECT * FROM workspaces WHERE id = ?",
                (GLOBAL_WORKSPACE_ID,),
            ).fetchone()
            assert created is not None
            return self._row_to_workspace(created)

    def list_workspaces(self) -> list[WorkspaceRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workspaces
                ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END, updated_at DESC
                """,
                (GLOBAL_WORKSPACE_ID,),
            ).fetchall()
        return [self._row_to_workspace(row) for row in rows]

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
        return self._row_to_workspace(row) if row is not None else None

    def get_workspace_by_path(self, root_path: str) -> WorkspaceRecord | None:
        normalized = _normalize_path(root_path)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM workspaces WHERE root_path = ?",
                (normalized,),
            ).fetchone()
        return self._row_to_workspace(row) if row is not None else None

    def upsert_workspace(
        self,
        *,
        root_path: str,
        name: str,
        kind: WorkspaceKind = "project",
        workspace_id: str | None = None,
    ) -> tuple[WorkspaceRecord, bool]:
        normalized = _normalize_path(root_path)
        now = time.time()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM workspaces WHERE root_path = ?",
                (normalized,),
            ).fetchone()
            if existing is not None:
                return self._row_to_workspace(existing), False

            ws_id = workspace_id or generate_workspace_id()
            ws_name = name.strip() or Path(normalized).name or normalized
            conn.execute(
                """
                INSERT INTO workspaces (id, name, root_path, kind, settings, created_at, updated_at)
                VALUES (?, ?, ?, ?, '{}', ?, ?)
                """,
                (ws_id, ws_name, normalized, kind, now, now),
            )
            row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (ws_id,)).fetchone()
            assert row is not None
            return self._row_to_workspace(row), True

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> WorkspaceRecord:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            if row is None:
                raise WorkspaceNotFoundError(f"Workspace '{workspace_id}' not found.")
            current = self._row_to_workspace(row)
            new_name = name.strip() if name is not None and name.strip() else current.name
            new_settings = settings if settings is not None else current.settings
            conn.execute(
                """
                UPDATE workspaces
                SET name = ?, settings = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_name, _dump_json(new_settings), now, workspace_id),
            )
            updated = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            assert updated is not None
            return self._row_to_workspace(updated)

    def delete_workspace(self, workspace_id: str) -> None:
        if workspace_id == GLOBAL_WORKSPACE_ID:
            raise WorkspaceProtectedError("The built-in 'global' workspace cannot be deleted.")
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
            if cur.rowcount == 0:
                raise WorkspaceNotFoundError(f"Workspace '{workspace_id}' not found.")

    def count_workspace_threads(self, workspace_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM threads WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
        return int(row["cnt"]) if row else 0

    # ------------------------------------------------------------------
    # Threads
    # ------------------------------------------------------------------

    def list_threads(self, workspace_id: str) -> list[ThreadRecord]:
        with self._connect() as conn:
            ws = conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            if ws is None:
                raise WorkspaceNotFoundError(f"Workspace '{workspace_id}' not found.")
            rows = conn.execute(
                "SELECT * FROM threads WHERE workspace_id = ? ORDER BY updated_at DESC",
                (workspace_id,),
            ).fetchall()
        return [self._row_to_thread(row) for row in rows]

    def get_thread(self, thread_id: str) -> ThreadRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        return self._row_to_thread(row) if row is not None else None

    def create_thread(
        self,
        *,
        workspace_id: str,
        thread_id: str | None = None,
        title: str = "",
        agent_id: str | None = None,
        model: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ThreadRecord:
        now = time.time()
        tid = (thread_id or "").strip() or generate_thread_id()
        with self._connect() as conn:
            ws = conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
            if ws is None:
                raise WorkspaceNotFoundError(f"Workspace '{workspace_id}' not found.")
            existing = conn.execute("SELECT 1 FROM threads WHERE id = ?", (tid,)).fetchone()
            if existing is not None:
                raise ThreadAlreadyExistsError(f"Thread '{tid}' already exists.")
            conn.execute(
                """
                INSERT INTO threads (
                    id, workspace_id, title, agent_id, model, status, settings, model_messages,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'idle', ?, ?, ?, ?)
                """,
                (
                    tid,
                    workspace_id,
                    title.strip(),
                    agent_id,
                    model,
                    _dump_json(settings or {}),
                    dump_messages([]),
                    now,
                    now,
                ),
            )
            conn.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now, workspace_id))
            row = conn.execute("SELECT * FROM threads WHERE id = ?", (tid,)).fetchone()
            assert row is not None
            return self._row_to_thread(row)

    def update_thread(
        self,
        thread_id: str,
        *,
        title: str | None = None,
        agent_id: str | None | object = _UNSET,
        model: str | None | object = _UNSET,
        status: ThreadStatus | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ThreadRecord:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if row is None:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
            current = self._row_to_thread(row)
            new_title = title.strip() if title is not None else current.title
            new_agent = current.agent_id if agent_id is _UNSET else agent_id
            new_model = current.model if model is _UNSET else model
            new_status = status if status is not None else current.status
            new_settings = settings if settings is not None else current.settings
            conn.execute(
                """
                UPDATE threads
                SET title = ?, agent_id = ?, model = ?, status = ?, settings = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_title,
                    new_agent,
                    new_model,
                    new_status,
                    _dump_json(new_settings),
                    now,
                    thread_id,
                ),
            )
            conn.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now, current.workspace_id))
            updated = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
            assert updated is not None
            return self._row_to_thread(updated)

    def delete_thread(self, thread_id: str) -> None:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM threads WHERE id = ?", (thread_id,))
            if cur.rowcount == 0:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")

    def clear_thread(self, thread_id: str) -> None:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute("SELECT workspace_id FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if row is None:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
            conn.execute("DELETE FROM items WHERE thread_id = ?", (thread_id,))
            conn.execute("DELETE FROM runs WHERE thread_id = ?", (thread_id,))
            conn.execute(
                """
                UPDATE threads
                SET model_messages = ?, status = 'idle', updated_at = ?
                WHERE id = ?
                """,
                (dump_messages([]), now, thread_id),
            )

    def load_model_messages(self, thread_id: str) -> list[ModelMessage]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT model_messages FROM threads WHERE id = ?",
                (thread_id,),
            ).fetchone()
            if row is None:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
            return load_messages(row["model_messages"])

    def save_model_messages(self, thread_id: str, messages: Sequence[ModelMessage]) -> None:
        now = time.time()
        blob = dump_messages(messages)
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE threads SET model_messages = ?, updated_at = ? WHERE id = ?",
                (blob, now, thread_id),
            )
            if cur.rowcount == 0:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def create_run(
        self,
        *,
        run_id: str,
        thread_id: str,
        workspace_id: str,
        agent_id: str,
        model: str,
        status: RunStatus = "running",
    ) -> RunRecord:
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, thread_id, workspace_id, agent_id, model, status, usage, error, started_at, ended_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, NULL)
                """,
                (run_id, thread_id, workspace_id, agent_id, model, status, now),
            )
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            assert row is not None
            return self._row_to_run(row)

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._row_to_run(row) if row is not None else None

    def list_runs(self, thread_id: str, *, limit: int = 50) -> list[RunRecord]:
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if exists is None:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
            rows = conn.execute(
                "SELECT * FROM runs WHERE thread_id = ? ORDER BY started_at DESC LIMIT ?",
                (thread_id, limit),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
        ended_at: float | None = None,
    ) -> RunRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                raise RunNotFoundError(f"Run '{run_id}' not found.")
            current = self._row_to_run(row)
            new_status = status if status is not None else current.status
            new_usage = usage if usage is not None else current.usage
            new_error = error if error is not None else current.error
            new_ended = ended_at if ended_at is not None else current.ended_at
            conn.execute(
                """
                UPDATE runs
                SET status = ?, usage = ?, error = ?, ended_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    _dump_json(new_usage) if new_usage is not None else None,
                    new_error,
                    new_ended,
                    run_id,
                ),
            )
            updated = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
            assert updated is not None
            return self._row_to_run(updated)

    def recover_interrupted_runs(self) -> int:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE runs
                SET status = 'cancelled', error = COALESCE(error, 'Daemon restarted during run'), ended_at = ?
                WHERE status IN ('running', 'waiting_approval')
                """,
                (now,),
            )
            conn.execute(
                """
                UPDATE items
                SET status = 'cancelled', updated_at = ?
                WHERE status = 'streaming'
                """,
                (now,),
            )
            conn.execute(
                """
                UPDATE threads
                SET status = 'idle', updated_at = ?
                WHERE status != 'idle'
                """,
                (now,),
            )
            return cur.rowcount

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def append_item(
        self,
        *,
        thread_id: str,
        run_id: str | None,
        kind: ItemKind,
        status: ItemStatus,
        payload: dict[str, Any],
        item_id: str | None = None,
    ) -> ItemRecord:
        now = time.time()
        iid = item_id or generate_item_id()
        with self._connect() as conn:
            row = conn.execute("SELECT workspace_id FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if row is None:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
            seq_row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM items WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
            next_seq = int(seq_row["next_seq"])
            conn.execute(
                """
                INSERT INTO items (id, thread_id, run_id, seq, kind, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (iid, thread_id, run_id, next_seq, kind, status, _dump_json(payload), now, now),
            )
            conn.execute("UPDATE threads SET updated_at = ? WHERE id = ?", (now, thread_id))
            conn.execute("UPDATE workspaces SET updated_at = ? WHERE id = ?", (now, row["workspace_id"]))
            created = conn.execute("SELECT * FROM items WHERE id = ?", (iid,)).fetchone()
            assert created is not None
            return self._row_to_item(created)

    def update_item(
        self,
        item_id: str,
        *,
        status: ItemStatus | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ItemRecord:
        now = time.time()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                raise LookupError(f"Item '{item_id}' not found.")
            current = self._row_to_item(row)
            new_status = status if status is not None else current.status
            new_payload = payload if payload is not None else current.payload
            conn.execute(
                """
                UPDATE items
                SET status = ?, payload = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, _dump_json(new_payload), now, item_id),
            )
            updated = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            assert updated is not None
            return self._row_to_item(updated)

    def get_item(self, item_id: str) -> ItemRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return self._row_to_item(row) if row is not None else None

    def list_items(
        self,
        thread_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> tuple[list[ItemRecord], bool]:
        with self._connect() as conn:
            exists = conn.execute("SELECT 1 FROM threads WHERE id = ?", (thread_id,)).fetchone()
            if exists is None:
                raise ThreadNotFoundError(f"Thread '{thread_id}' not found.")
            rows = conn.execute(
                """
                SELECT * FROM items
                WHERE thread_id = ? AND seq > ?
                ORDER BY seq ASC
                LIMIT ?
                """,
                (thread_id, after_seq, limit + 1),
            ).fetchall()
        has_more = len(rows) > limit
        items = [self._row_to_item(row) for row in rows[:limit]]
        return items, has_more

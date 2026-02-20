from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Sequence

from pydantic_ai.messages import ModelMessage

from lattis.domain.messages import dump_messages, load_messages
from lattis.domain.schedules import (
    SCHEDULE_STATUS_CANCELED,
    SCHEDULE_STATUS_DONE,
    SCHEDULE_STATUS_PENDING,
    SCHEDULE_STATUS_RUNNING,
    ScheduleRecord,
)
from lattis.domain.sessions import SessionStore, ThreadSettings, ThreadState


class SQLiteSessionStore(SessionStore):
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def load_thread(
        self,
        session_id: str,
        thread_id: str,
    ) -> ThreadState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT messages FROM threads WHERE session_id = ? AND thread_id = ?",
                (session_id, thread_id),
            ).fetchone()
            if row:
                messages_blob = row[0]
                messages = load_messages(messages_blob)
                return ThreadState(
                    session_id=session_id,
                    thread_id=thread_id,
                    messages=messages,
                )
        return None

    def save_thread(
        self,
        session_id: str,
        thread_id: str,
        *,
        messages: Sequence[ModelMessage],
    ) -> None:
        with self._connect() as conn:
            self._upsert_thread(conn, session_id, thread_id, list(messages))

    def list_threads(self, session_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT thread_id FROM threads WHERE session_id = ? ORDER BY updated_at DESC",
                (session_id,),
            ).fetchall()
        return [row[0] for row in rows]

    def thread_exists(self, session_id: str, thread_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM threads WHERE session_id = ? AND thread_id = ? LIMIT 1",
                (session_id, thread_id),
            ).fetchone()
        return row is not None

    def list_sessions(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT session_id FROM sessions ORDER BY updated_at DESC").fetchall()
        return [row[0] for row in rows]

    def delete_thread(self, session_id: str, thread_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM threads WHERE session_id = ? AND thread_id = ?",
                (session_id, thread_id),
            )
            conn.execute(
                "DELETE FROM thread_settings WHERE session_id = ? AND thread_id = ?",
                (session_id, thread_id),
            )
            conn.execute(
                "DELETE FROM schedules WHERE session_id = ? AND thread_id = ?",
                (session_id, thread_id),
            )
            remaining = conn.execute(
                "SELECT 1 FROM threads WHERE session_id = ? LIMIT 1",
                (session_id,),
            ).fetchone()
            if remaining is None:
                conn.execute(
                    "DELETE FROM sessions WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM session_settings WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM thread_settings WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM schedules WHERE session_id = ?",
                    (session_id,),
                )

    def get_session_model(self, session_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT model FROM session_settings WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return None
        return row[0]

    def set_session_model(self, session_id: str, model: str | None) -> None:
        with self._connect() as conn:
            now = time.time()
            self._touch_session(conn, session_id, now=now)
            conn.execute(
                """
                INSERT INTO session_settings (session_id, model, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    model = excluded.model,
                    updated_at = excluded.updated_at
                """,
                (session_id, model, now),
            )

    def get_thread_settings(self, session_id: str, thread_id: str) -> ThreadSettings:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT settings FROM thread_settings WHERE session_id = ? AND thread_id = ?",
                (session_id, thread_id),
            ).fetchone()
        if row and row[0]:
            try:
                data = json.loads(row[0])
                if isinstance(data, dict):
                    return ThreadSettings.model_validate(data)
            except Exception:
                pass

        # Best-effort migration from the legacy `threads.agent` column.
        try:
            with self._connect() as conn:
                legacy = conn.execute(
                    "SELECT agent FROM threads WHERE session_id = ? AND thread_id = ?",
                    (session_id, thread_id),
                ).fetchone()
            if legacy and legacy[0]:
                return ThreadSettings(agent=str(legacy[0]))
        except sqlite3.Error:
            pass

        return ThreadSettings()

    def set_thread_settings(self, session_id: str, thread_id: str, settings: ThreadSettings) -> None:
        now = time.time()
        payload = settings.model_dump(mode="json", exclude_none=True)
        settings_json = json.dumps(payload, ensure_ascii=True)
        with self._connect() as conn:
            self._touch_session(conn, session_id, now=now)
            self._touch_thread(conn, session_id, thread_id, now=now)
            conn.execute(
                """
                INSERT INTO thread_settings (session_id, thread_id, created_at, updated_at, settings)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, thread_id) DO UPDATE SET
                    updated_at = excluded.updated_at,
                    settings = excluded.settings
                """,
                (session_id, thread_id, now, now, settings_json),
            )

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def create_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        prompt: str,
        due_at: float,
        interval_seconds: int | None,
        created_at: float,
    ) -> ScheduleRecord:
        with self._connect() as conn:
            self._touch_session(conn, session_id, now=created_at)
            self._touch_thread(conn, session_id, thread_id, now=created_at)
            conn.execute(
                """
                INSERT INTO schedules (
                    schedule_id, session_id, thread_id, prompt, due_at,
                    interval_seconds, status, lease_expires_at,
                    attempt_count, last_error, last_run_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, NULL, ?, ?)
                """,
                (
                    schedule_id,
                    session_id,
                    thread_id,
                    prompt,
                    due_at,
                    interval_seconds,
                    SCHEDULE_STATUS_PENDING,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        assert row is not None
        return self._schedule_from_row(row)

    def get_schedule_record(self, schedule_id: str) -> ScheduleRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._schedule_from_row(row) if row else None

    def list_schedule_records(
        self,
        *,
        session_id: str,
        thread_id: str,
        include_terminal: bool,
        limit: int,
    ) -> list[ScheduleRecord]:
        bounded_limit = max(1, min(limit, 100))
        with self._connect() as conn:
            if include_terminal:
                rows = conn.execute(
                    """
                    SELECT * FROM schedules
                    WHERE session_id = ? AND thread_id = ?
                    ORDER BY due_at ASC, created_at ASC
                    LIMIT ?
                    """,
                    (session_id, thread_id, bounded_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM schedules
                    WHERE session_id = ? AND thread_id = ? AND status IN (?, ?)
                    ORDER BY due_at ASC, created_at ASC
                    LIMIT ?
                    """,
                    (
                        session_id,
                        thread_id,
                        SCHEDULE_STATUS_PENDING,
                        SCHEDULE_STATUS_RUNNING,
                        bounded_limit,
                    ),
                ).fetchall()
        return [self._schedule_from_row(row) for row in rows]

    def update_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        prompt: str,
        due_at: float,
        interval_seconds: int | None,
        updated_at: float,
    ) -> ScheduleRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE schedules
                SET prompt = ?,
                    due_at = ?,
                    interval_seconds = ?,
                    updated_at = ?
                WHERE schedule_id = ?
                  AND session_id = ?
                  AND thread_id = ?
                  AND status IN (?, ?)
                """,
                (
                    prompt,
                    due_at,
                    interval_seconds,
                    updated_at,
                    schedule_id,
                    session_id,
                    thread_id,
                    SCHEDULE_STATUS_PENDING,
                    SCHEDULE_STATUS_RUNNING,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._schedule_from_row(row) if row else None

    def cancel_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        canceled_at: float,
    ) -> ScheduleRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE schedules
                SET status = ?,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE schedule_id = ?
                  AND session_id = ?
                  AND thread_id = ?
                  AND status IN (?, ?)
                """,
                (
                    SCHEDULE_STATUS_CANCELED,
                    canceled_at,
                    schedule_id,
                    session_id,
                    thread_id,
                    SCHEDULE_STATUS_PENDING,
                    SCHEDULE_STATUS_RUNNING,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._schedule_from_row(row) if row else None

    def claim_due_schedule_records(
        self,
        *,
        now: float,
        limit: int,
        lease_seconds: int,
    ) -> list[ScheduleRecord]:
        bounded_limit = max(1, min(limit, 100))
        lease_expires_at = now + max(1, lease_seconds)
        claimed_rows: list[sqlite3.Row] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM schedules
                WHERE (
                    (status = ? AND due_at <= ?)
                    OR (status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                )
                ORDER BY due_at ASC, created_at ASC
                LIMIT ?
                """,
                (
                    SCHEDULE_STATUS_PENDING,
                    now,
                    SCHEDULE_STATUS_RUNNING,
                    now,
                    bounded_limit,
                ),
            ).fetchall()
            for row in rows:
                schedule_id = row["schedule_id"]
                cursor = conn.execute(
                    """
                    UPDATE schedules
                    SET status = ?,
                        lease_expires_at = ?,
                        updated_at = ?
                    WHERE schedule_id = ?
                      AND (
                        (status = ? AND due_at <= ?)
                        OR (status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                      )
                    """,
                    (
                        SCHEDULE_STATUS_RUNNING,
                        lease_expires_at,
                        now,
                        schedule_id,
                        SCHEDULE_STATUS_PENDING,
                        now,
                        SCHEDULE_STATUS_RUNNING,
                        now,
                    ),
                )
                if cursor.rowcount == 0:
                    continue
                claimed = conn.execute(
                    "SELECT * FROM schedules WHERE schedule_id = ?",
                    (schedule_id,),
                ).fetchone()
                if claimed is not None:
                    claimed_rows.append(claimed)
        return [self._schedule_from_row(row) for row in claimed_rows]

    def complete_claimed_schedule_record(
        self,
        *,
        schedule_id: str,
        completed_at: float,
        next_due_at: float | None,
    ) -> ScheduleRecord | None:
        if next_due_at is None:
            next_status = SCHEDULE_STATUS_DONE
            due_value = completed_at
        else:
            next_status = SCHEDULE_STATUS_PENDING
            due_value = next_due_at

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE schedules
                SET status = ?,
                    due_at = ?,
                    lease_expires_at = NULL,
                    attempt_count = attempt_count + 1,
                    last_error = NULL,
                    last_run_at = ?,
                    updated_at = ?
                WHERE schedule_id = ?
                  AND status = ?
                """,
                (
                    next_status,
                    due_value,
                    completed_at,
                    completed_at,
                    schedule_id,
                    SCHEDULE_STATUS_RUNNING,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._schedule_from_row(row) if row else None

    def fail_claimed_schedule_record(
        self,
        *,
        schedule_id: str,
        failed_at: float,
        retry_at: float,
        error: str,
    ) -> ScheduleRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE schedules
                SET status = ?,
                    due_at = ?,
                    lease_expires_at = NULL,
                    attempt_count = attempt_count + 1,
                    last_error = ?,
                    updated_at = ?
                WHERE schedule_id = ?
                  AND status = ?
                """,
                (
                    SCHEDULE_STATUS_PENDING,
                    retry_at,
                    error,
                    failed_at,
                    schedule_id,
                    SCHEDULE_STATUS_RUNNING,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._schedule_from_row(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    messages BLOB,
                    PRIMARY KEY (session_id, thread_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS thread_settings (
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    settings TEXT,
                    PRIMARY KEY (session_id, thread_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_settings (
                    session_id TEXT PRIMARY KEY,
                    model TEXT,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    due_at REAL NOT NULL,
                    interval_seconds INTEGER,
                    status TEXT NOT NULL,
                    lease_expires_at REAL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_run_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_schedules_due_status
                ON schedules(status, due_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_schedules_thread
                ON schedules(session_id, thread_id, updated_at)
                """
            )

    def _touch_session(self, conn: sqlite3.Connection, session_id: str, *, now: float) -> None:
        conn.execute(
            """
            INSERT INTO sessions (session_id, created_at, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (session_id, now, now),
        )

    def _touch_thread(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        thread_id: str,
        *,
        now: float,
    ) -> None:
        conn.execute(
            """
            INSERT INTO threads (session_id, thread_id, created_at, updated_at, messages)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, thread_id) DO UPDATE SET
                updated_at = excluded.updated_at
            """,
            (session_id, thread_id, now, now, dump_messages([])),
        )

    def _upsert_thread(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        thread_id: str,
        messages: list[ModelMessage],
    ) -> None:
        now = time.time()
        self._touch_session(conn, session_id, now=now)
        messages_blob = dump_messages(messages)
        conn.execute(
            """
            INSERT INTO threads (session_id, thread_id, created_at, updated_at, messages)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, thread_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                messages = excluded.messages
            """,
            (session_id, thread_id, now, now, messages_blob),
        )

    @staticmethod
    def _schedule_from_row(row: sqlite3.Row) -> ScheduleRecord:
        return ScheduleRecord(
            schedule_id=row["schedule_id"],
            session_id=row["session_id"],
            thread_id=row["thread_id"],
            prompt=row["prompt"],
            due_at=float(row["due_at"]),
            interval_seconds=int(row["interval_seconds"]) if row["interval_seconds"] is not None else None,
            status=str(row["status"]),
            lease_expires_at=float(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
            attempt_count=int(row["attempt_count"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            last_run_at=float(row["last_run_at"]) if row["last_run_at"] is not None else None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

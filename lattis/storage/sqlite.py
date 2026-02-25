from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from pydantic_ai.messages import ModelMessage

from lattis.domain.channels import ChannelBindingRecord
from lattis.domain.messages import dump_messages, load_messages
from lattis.domain.outbox import (
    OUTBOX_STATUS_DEAD,
    OUTBOX_STATUS_LEASED,
    OUTBOX_STATUS_QUEUED,
    OUTBOX_STATUS_SENT,
    NotificationOutboxRecord,
)
from lattis.domain.schedules import (
    SCHEDULE_RUN_STATUS_RUNNING,
    SCHEDULE_STATUS_CANCELED,
    SCHEDULE_STATUS_DONE,
    SCHEDULE_STATUS_PENDING,
    SCHEDULE_STATUS_RUNNING,
    SCHEDULE_TRIGGER_CRON,
    ScheduleRecord,
    ScheduleRunRecord,
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
            conn.execute(
                "DELETE FROM schedule_runs WHERE session_id = ? AND thread_id = ?",
                (session_id, thread_id),
            )
            conn.execute(
                "DELETE FROM channel_bindings WHERE session_id = ? AND thread_id = ?",
                (session_id, thread_id),
            )
            conn.execute(
                "DELETE FROM notification_outbox WHERE session_id = ? AND thread_id = ?",
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
                conn.execute(
                    "DELETE FROM schedule_runs WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM channel_bindings WHERE session_id = ?",
                    (session_id,),
                )
                conn.execute(
                    "DELETE FROM notification_outbox WHERE session_id = ?",
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
    # Channel bindings
    # ------------------------------------------------------------------

    def get_channel_binding_record(
        self,
        *,
        channel: str,
        external_conversation_id: str,
    ) -> ChannelBindingRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM channel_bindings
                WHERE channel = ? AND external_conversation_id = ?
                LIMIT 1
                """,
                (channel, external_conversation_id),
            ).fetchone()
        return self._channel_binding_from_row(row) if row else None

    def upsert_channel_binding_record(
        self,
        *,
        binding_id: str,
        session_id: str,
        thread_id: str,
        channel: str,
        external_conversation_id: str,
        external_user_id: str | None,
        metadata_json: dict[str, Any] | None,
        updated_at: float,
    ) -> ChannelBindingRecord:
        metadata_blob = (
            json.dumps(metadata_json, ensure_ascii=True, separators=(",", ":"))
            if metadata_json is not None
            else None
        )
        with self._connect() as conn:
            self._touch_session(conn, session_id, now=updated_at)
            self._touch_thread(conn, session_id, thread_id, now=updated_at)
            conn.execute(
                """
                INSERT INTO channel_bindings (
                    binding_id,
                    session_id,
                    thread_id,
                    channel,
                    external_conversation_id,
                    external_user_id,
                    metadata_json,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(channel, external_conversation_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    thread_id = excluded.thread_id,
                    external_user_id = excluded.external_user_id,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    binding_id,
                    session_id,
                    thread_id,
                    channel,
                    external_conversation_id,
                    external_user_id,
                    metadata_blob,
                    updated_at,
                    updated_at,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM channel_bindings
                WHERE channel = ? AND external_conversation_id = ?
                LIMIT 1
                """,
                (channel, external_conversation_id),
            ).fetchone()
        assert row is not None
        return self._channel_binding_from_row(row)

    def list_thread_channel_bindings(
        self,
        *,
        session_id: str,
        thread_id: str,
    ) -> list[ChannelBindingRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM channel_bindings
                WHERE session_id = ? AND thread_id = ?
                ORDER BY created_at ASC
                """,
                (session_id, thread_id),
            ).fetchall()
        return [self._channel_binding_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    # Notification outbox
    # ------------------------------------------------------------------

    def enqueue_notification_outbox_record(
        self,
        *,
        outbox_id: str,
        session_id: str,
        thread_id: str,
        schedule_id: str | None,
        schedule_run_id: str | None,
        channel: str,
        external_conversation_id: str,
        payload_json: dict[str, Any],
        dedupe_key: str,
        available_at: float,
        created_at: float,
    ) -> NotificationOutboxRecord:
        payload_blob = json.dumps(payload_json, ensure_ascii=True, separators=(",", ":"))
        with self._connect() as conn:
            self._touch_session(conn, session_id, now=created_at)
            self._touch_thread(conn, session_id, thread_id, now=created_at)
            conn.execute(
                """
                INSERT INTO notification_outbox (
                    outbox_id,
                    session_id,
                    thread_id,
                    schedule_id,
                    schedule_run_id,
                    channel,
                    external_conversation_id,
                    payload_json,
                    dedupe_key,
                    status,
                    attempt_count,
                    available_at,
                    lease_expires_at,
                    last_error,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, NULL, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (
                    outbox_id,
                    session_id,
                    thread_id,
                    schedule_id,
                    schedule_run_id,
                    channel,
                    external_conversation_id,
                    payload_blob,
                    dedupe_key,
                    OUTBOX_STATUS_QUEUED,
                    available_at,
                    created_at,
                    created_at,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM notification_outbox
                WHERE dedupe_key = ?
                LIMIT 1
                """,
                (dedupe_key,),
            ).fetchone()
        assert row is not None
        return self._outbox_from_row(row)

    def claim_notification_outbox_records(
        self,
        *,
        now: float,
        limit: int,
        lease_seconds: int,
    ) -> list[NotificationOutboxRecord]:
        bounded_limit = max(1, min(limit, 100))
        lease_expires_at = now + max(1, lease_seconds)
        claimed_rows: list[sqlite3.Row] = []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM notification_outbox
                WHERE (
                    (status = ? AND available_at <= ?)
                    OR (status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                )
                ORDER BY available_at ASC, created_at ASC
                LIMIT ?
                """,
                (
                    OUTBOX_STATUS_QUEUED,
                    now,
                    OUTBOX_STATUS_LEASED,
                    now,
                    bounded_limit,
                ),
            ).fetchall()

            for row in rows:
                outbox_id = str(row["outbox_id"])
                cursor = conn.execute(
                    """
                    UPDATE notification_outbox
                    SET status = ?,
                        lease_expires_at = ?,
                        attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE outbox_id = ?
                      AND (
                        (status = ? AND available_at <= ?)
                        OR (status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                      )
                    """,
                    (
                        OUTBOX_STATUS_LEASED,
                        lease_expires_at,
                        now,
                        outbox_id,
                        OUTBOX_STATUS_QUEUED,
                        now,
                        OUTBOX_STATUS_LEASED,
                        now,
                    ),
                )
                if cursor.rowcount == 0:
                    continue
                claimed = conn.execute(
                    "SELECT * FROM notification_outbox WHERE outbox_id = ?",
                    (outbox_id,),
                ).fetchone()
                if claimed is not None:
                    claimed_rows.append(claimed)

        return [self._outbox_from_row(row) for row in claimed_rows]

    def mark_notification_outbox_record_sent(
        self,
        *,
        outbox_id: str,
        sent_at: float,
    ) -> NotificationOutboxRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE notification_outbox
                SET status = ?,
                    lease_expires_at = NULL,
                    last_error = NULL,
                    updated_at = ?
                WHERE outbox_id = ?
                  AND status = ?
                """,
                (
                    OUTBOX_STATUS_SENT,
                    sent_at,
                    outbox_id,
                    OUTBOX_STATUS_LEASED,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM notification_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
        return self._outbox_from_row(row) if row else None

    def mark_notification_outbox_record_retry(
        self,
        *,
        outbox_id: str,
        retry_at: float,
        failed_at: float,
        error: str,
    ) -> NotificationOutboxRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE notification_outbox
                SET status = ?,
                    available_at = ?,
                    lease_expires_at = NULL,
                    last_error = ?,
                    updated_at = ?
                WHERE outbox_id = ?
                  AND status = ?
                """,
                (
                    OUTBOX_STATUS_QUEUED,
                    retry_at,
                    error,
                    failed_at,
                    outbox_id,
                    OUTBOX_STATUS_LEASED,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM notification_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
        return self._outbox_from_row(row) if row else None

    def mark_notification_outbox_record_dead(
        self,
        *,
        outbox_id: str,
        failed_at: float,
        error: str,
    ) -> NotificationOutboxRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE notification_outbox
                SET status = ?,
                    lease_expires_at = NULL,
                    last_error = ?,
                    updated_at = ?
                WHERE outbox_id = ?
                  AND status = ?
                """,
                (
                    OUTBOX_STATUS_DEAD,
                    error,
                    failed_at,
                    outbox_id,
                    OUTBOX_STATUS_LEASED,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM notification_outbox WHERE outbox_id = ?",
                (outbox_id,),
            ).fetchone()
        return self._outbox_from_row(row) if row else None

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def create_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        name: str,
        prompt: str,
        trigger_type: str,
        run_at: float | None,
        cron: str | None,
        timezone: str | None,
        next_run_at: float,
        enabled: bool,
        protected: bool,
        created_at: float,
    ) -> ScheduleRecord:
        with self._connect() as conn:
            self._touch_session(conn, session_id, now=created_at)
            self._touch_thread(conn, session_id, thread_id, now=created_at)
            conn.execute(
                """
                INSERT INTO schedules (
                    schedule_id, session_id, thread_id, name, prompt,
                    trigger_type, run_at, cron, timezone,
                    next_run_at, enabled, protected,
                    status, lease_expires_at,
                    attempt_count, last_error, last_run_at,
                    state_json, state_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, NULL, NULL, 0, ?, ?)
                """,
                (
                    schedule_id,
                    session_id,
                    thread_id,
                    name,
                    prompt,
                    trigger_type,
                    run_at,
                    cron,
                    timezone,
                    next_run_at,
                    1 if enabled else 0,
                    1 if protected else 0,
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

    def upsert_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        name: str,
        prompt: str,
        trigger_type: str,
        run_at: float | None,
        cron: str | None,
        timezone: str | None,
        next_run_at: float,
        enabled: bool,
        protected: bool,
        now: float,
    ) -> ScheduleRecord:
        with self._connect() as conn:
            self._touch_session(conn, session_id, now=now)
            self._touch_thread(conn, session_id, thread_id, now=now)
            conn.execute(
                """
                INSERT INTO schedules (
                    schedule_id, session_id, thread_id, name, prompt,
                    trigger_type, run_at, cron, timezone,
                    next_run_at, enabled, protected,
                    status, lease_expires_at,
                    attempt_count, last_error, last_run_at,
                    state_json, state_version,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, NULL, NULL, 0, ?, ?)
                ON CONFLICT(session_id, thread_id, name) DO UPDATE SET
                    prompt = excluded.prompt,
                    trigger_type = excluded.trigger_type,
                    run_at = excluded.run_at,
                    cron = excluded.cron,
                    timezone = excluded.timezone,
                    next_run_at = excluded.next_run_at,
                    enabled = excluded.enabled,
                    protected = CASE WHEN schedules.protected = 1 THEN 1 ELSE excluded.protected END,
                    status = CASE WHEN schedules.status = ? THEN schedules.status ELSE ? END,
                    lease_expires_at = CASE
                        WHEN schedules.status = ? THEN schedules.lease_expires_at
                        ELSE NULL
                    END,
                    last_error = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    schedule_id,
                    session_id,
                    thread_id,
                    name,
                    prompt,
                    trigger_type,
                    run_at,
                    cron,
                    timezone,
                    next_run_at,
                    1 if enabled else 0,
                    1 if protected else 0,
                    SCHEDULE_STATUS_PENDING,
                    now,
                    now,
                    SCHEDULE_STATUS_RUNNING,
                    SCHEDULE_STATUS_PENDING,
                    SCHEDULE_STATUS_RUNNING,
                ),
            )
            row = conn.execute(
                """
                SELECT * FROM schedules
                WHERE session_id = ? AND thread_id = ? AND name = ?
                LIMIT 1
                """,
                (session_id, thread_id, name),
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

    def get_schedule_record_by_name(
        self,
        *,
        session_id: str,
        thread_id: str,
        name: str,
    ) -> ScheduleRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM schedules
                WHERE session_id = ? AND thread_id = ? AND name = ?
                LIMIT 1
                """,
                (session_id, thread_id, name),
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
                    ORDER BY next_run_at ASC, created_at ASC
                    LIMIT ?
                    """,
                    (session_id, thread_id, bounded_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM schedules
                    WHERE session_id = ? AND thread_id = ? AND status IN (?, ?)
                    ORDER BY next_run_at ASC, created_at ASC
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
        name: str,
        prompt: str,
        trigger_type: str,
        run_at: float | None,
        cron: str | None,
        timezone: str | None,
        next_run_at: float,
        enabled: bool,
        updated_at: float,
    ) -> ScheduleRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE schedules
                SET name = ?,
                    prompt = ?,
                    trigger_type = ?,
                    run_at = ?,
                    cron = ?,
                    timezone = ?,
                    next_run_at = ?,
                    enabled = ?,
                    updated_at = ?
                WHERE schedule_id = ?
                  AND session_id = ?
                  AND thread_id = ?
                  AND status IN (?, ?)
                """,
                (
                    name,
                    prompt,
                    trigger_type,
                    run_at,
                    cron,
                    timezone,
                    next_run_at,
                    1 if enabled else 0,
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
                    (status = ? AND enabled = 1 AND next_run_at <= ?)
                    OR (status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?)
                )
                ORDER BY next_run_at ASC, created_at ASC
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
                        (status = ? AND enabled = 1 AND next_run_at <= ?)
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
                    next_run_at = ?,
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
                    next_run_at = ?,
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

    def delete_schedule_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM schedules
                WHERE schedule_id = ?
                  AND session_id = ?
                  AND thread_id = ?
                """,
                (schedule_id, session_id, thread_id),
            )
            return cursor.rowcount > 0

    def set_schedule_state_record(
        self,
        *,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        state_json: dict[str, object] | None,
        expected_version: int | None,
        updated_at: float,
    ) -> ScheduleRecord | None:
        payload = json.dumps(state_json, ensure_ascii=True, separators=(",", ":")) if state_json is not None else None
        with self._connect() as conn:
            if expected_version is None:
                cursor = conn.execute(
                    """
                    UPDATE schedules
                    SET state_json = ?,
                        state_version = state_version + 1,
                        updated_at = ?
                    WHERE schedule_id = ?
                      AND session_id = ?
                      AND thread_id = ?
                      AND status IN (?, ?)
                    """,
                    (
                        payload,
                        updated_at,
                        schedule_id,
                        session_id,
                        thread_id,
                        SCHEDULE_STATUS_PENDING,
                        SCHEDULE_STATUS_RUNNING,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE schedules
                    SET state_json = ?,
                        state_version = state_version + 1,
                        updated_at = ?
                    WHERE schedule_id = ?
                      AND session_id = ?
                      AND thread_id = ?
                      AND status IN (?, ?)
                      AND state_version = ?
                    """,
                    (
                        payload,
                        updated_at,
                        schedule_id,
                        session_id,
                        thread_id,
                        SCHEDULE_STATUS_PENDING,
                        SCHEDULE_STATUS_RUNNING,
                        expected_version,
                    ),
                )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        return self._schedule_from_row(row) if row else None

    def create_schedule_run_record(
        self,
        *,
        run_id: str,
        schedule_id: str,
        session_id: str,
        thread_id: str,
        trigger_prompt: str,
        started_at: float,
    ) -> ScheduleRunRecord:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO schedule_runs (
                    run_id, schedule_id, session_id, thread_id, status,
                    trigger_prompt, result_text, error, notified_count,
                    started_at, finished_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, 0, ?, NULL, ?, ?)
                """,
                (
                    run_id,
                    schedule_id,
                    session_id,
                    thread_id,
                    SCHEDULE_RUN_STATUS_RUNNING,
                    trigger_prompt,
                    started_at,
                    started_at,
                    started_at,
                ),
            )
            row = conn.execute(
                "SELECT * FROM schedule_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        assert row is not None
        return self._schedule_run_from_row(row)

    def finish_schedule_run_record(
        self,
        *,
        run_id: str,
        status: str,
        result_text: str | None,
        error: str | None,
        notified_count: int,
        finished_at: float,
    ) -> ScheduleRunRecord | None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE schedule_runs
                SET status = ?,
                    result_text = ?,
                    error = ?,
                    notified_count = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status,
                    result_text,
                    error,
                    max(0, notified_count),
                    finished_at,
                    finished_at,
                    run_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                "SELECT * FROM schedule_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return self._schedule_run_from_row(row) if row else None

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
                CREATE TABLE IF NOT EXISTS channel_bindings (
                    binding_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    external_conversation_id TEXT NOT NULL,
                    external_user_id TEXT,
                    metadata_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(channel, external_conversation_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_channel_bindings_thread
                ON channel_bindings(session_id, thread_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notification_outbox (
                    outbox_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    schedule_id TEXT,
                    schedule_run_id TEXT,
                    channel TEXT NOT NULL,
                    external_conversation_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL,
                    lease_expires_at REAL,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notification_outbox_status
                ON notification_outbox(status, available_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notification_outbox_thread
                ON notification_outbox(session_id, thread_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedules (
                    schedule_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    run_at REAL,
                    cron TEXT,
                    timezone TEXT,
                    next_run_at REAL NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    protected INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    lease_expires_at REAL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_run_at REAL,
                    state_json TEXT,
                    state_version INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_id, thread_id, name)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_schedules_due_status
                ON schedules(status, enabled, next_run_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_schedules_thread
                ON schedules(session_id, thread_id, updated_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_runs (
                    run_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_prompt TEXT NOT NULL,
                    result_text TEXT,
                    error TEXT,
                    notified_count INTEGER NOT NULL DEFAULT 0,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_schedule_runs_schedule
                ON schedule_runs(schedule_id, started_at DESC)
                """
            )
            self._ensure_schedule_schema(conn)

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
        self._ensure_thread_heartbeat_schedule(conn, session_id=session_id, thread_id=thread_id, now=now)

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
        self._ensure_thread_heartbeat_schedule(conn, session_id=session_id, thread_id=thread_id, now=now)

    def _ensure_thread_heartbeat_schedule(
        self,
        conn: sqlite3.Connection,
        *,
        session_id: str,
        thread_id: str,
        now: float,
    ) -> None:
        # The heartbeat schedule is created by default for every thread.
        # It can be edited/disabled, but must never be deleted.
        next_run_at = (int(now) // 3600 + 1) * 3600
        schedule_id = f"sched-heartbeat-{uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT OR IGNORE INTO schedules (
                schedule_id, session_id, thread_id, name, prompt,
                trigger_type, run_at, cron, timezone,
                next_run_at, enabled, protected,
                status, lease_expires_at,
                attempt_count, last_error, last_run_at,
                state_json, state_version,
                created_at, updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?,
                ?, NULL, ?, ?,
                ?, 1, 1,
                ?, NULL,
                0, NULL, NULL,
                NULL, 0,
                ?, ?
            )
            """,
            (
                schedule_id,
                session_id,
                thread_id,
                "heartbeat",
                (
                    "Heartbeat background loop.\n\n"
                    "Every hour, do lightweight, useful background work for this thread:\n"
                    "- Scan the thread for open tasks, unanswered questions, or TODOs.\n"
                    "- Make incremental progress (research, drafts, checks, summaries, code maintenance).\n"
                    "- Use schedule_state_get / schedule_state_set to remember cursors and avoid repeating work.\n\n"
                    "Only call notify_user when you have a concrete, user-visible update or an urgent issue.\n"
                    "If there's nothing worth notifying, do not notify the user."
                ),
                SCHEDULE_TRIGGER_CRON,
                "0 * * * *",
                "UTC",
                float(next_run_at),
                SCHEDULE_STATUS_PENDING,
                now,
                now,
            ),
        )

    @staticmethod
    def _channel_binding_from_row(row: sqlite3.Row) -> ChannelBindingRecord:
        metadata_json: dict[str, Any] | None = None
        raw_metadata = row["metadata_json"] if "metadata_json" in row.keys() else None
        if isinstance(raw_metadata, str) and raw_metadata:
            try:
                loaded = json.loads(raw_metadata)
                if isinstance(loaded, dict):
                    metadata_json = loaded
            except Exception:
                metadata_json = None

        return ChannelBindingRecord(
            binding_id=str(row["binding_id"]),
            session_id=str(row["session_id"]),
            thread_id=str(row["thread_id"]),
            channel=str(row["channel"]),
            external_conversation_id=str(row["external_conversation_id"]),
            external_user_id=str(row["external_user_id"]) if row["external_user_id"] is not None else None,
            metadata_json=metadata_json,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _outbox_from_row(row: sqlite3.Row) -> NotificationOutboxRecord:
        payload_json: dict[str, Any] = {}
        raw_payload = row["payload_json"] if "payload_json" in row.keys() else None
        if isinstance(raw_payload, str) and raw_payload:
            try:
                loaded = json.loads(raw_payload)
                if isinstance(loaded, dict):
                    payload_json = loaded
            except Exception:
                payload_json = {}

        return NotificationOutboxRecord(
            outbox_id=str(row["outbox_id"]),
            session_id=str(row["session_id"]),
            thread_id=str(row["thread_id"]),
            schedule_id=str(row["schedule_id"]) if row["schedule_id"] is not None else None,
            schedule_run_id=str(row["schedule_run_id"]) if row["schedule_run_id"] is not None else None,
            channel=str(row["channel"]),
            external_conversation_id=str(row["external_conversation_id"]),
            payload_json=payload_json,
            dedupe_key=str(row["dedupe_key"]),
            status=str(row["status"]),
            attempt_count=int(row["attempt_count"]),
            available_at=float(row["available_at"]),
            lease_expires_at=float(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _schedule_from_row(row: sqlite3.Row) -> ScheduleRecord:
        keys = set(row.keys())
        state_json: dict[str, object] | None = None
        raw_state = row["state_json"] if "state_json" in keys else None
        if isinstance(raw_state, str) and raw_state:
            try:
                loaded = json.loads(raw_state)
                if isinstance(loaded, dict):
                    state_json = loaded
            except Exception:
                state_json = None

        next_run_at: float
        if "next_run_at" in keys and row["next_run_at"] is not None:
            next_run_at = float(row["next_run_at"])
        else:
            next_run_at = float(row["due_at"])  # legacy column

        return ScheduleRecord(
            schedule_id=row["schedule_id"],
            session_id=row["session_id"],
            thread_id=row["thread_id"],
            name=str(row["name"]) if "name" in keys and row["name"] is not None else "",
            prompt=row["prompt"],
            trigger_type=str(row["trigger_type"]) if "trigger_type" in keys and row["trigger_type"] is not None else "once",
            run_at=float(row["run_at"]) if "run_at" in keys and row["run_at"] is not None else None,
            cron=str(row["cron"]) if "cron" in keys and row["cron"] is not None else None,
            timezone=str(row["timezone"]) if "timezone" in keys and row["timezone"] is not None else None,
            next_run_at=next_run_at,
            enabled=bool(int(row["enabled"])) if "enabled" in keys and row["enabled"] is not None else True,
            protected=bool(int(row["protected"])) if "protected" in keys and row["protected"] is not None else False,
            status=str(row["status"]),
            lease_expires_at=float(row["lease_expires_at"]) if row["lease_expires_at"] is not None else None,
            attempt_count=int(row["attempt_count"]),
            last_error=str(row["last_error"]) if row["last_error"] is not None else None,
            last_run_at=float(row["last_run_at"]) if row["last_run_at"] is not None else None,
            state_json=state_json,
            state_version=int(row["state_version"]) if "state_version" in keys and row["state_version"] is not None else 0,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _schedule_run_from_row(row: sqlite3.Row) -> ScheduleRunRecord:
        return ScheduleRunRecord(
            run_id=row["run_id"],
            schedule_id=row["schedule_id"],
            session_id=row["session_id"],
            thread_id=row["thread_id"],
            status=row["status"],
            trigger_prompt=row["trigger_prompt"],
            result_text=str(row["result_text"]) if row["result_text"] is not None else None,
            error=str(row["error"]) if row["error"] is not None else None,
            notified_count=int(row["notified_count"]),
            started_at=float(row["started_at"]),
            finished_at=float(row["finished_at"]) if row["finished_at"] is not None else None,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def _ensure_schedule_schema(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(schedules)").fetchall() if len(row) >= 2}

        # Clean cutover migration: if the legacy schema is detected, move it aside
        # and create a fresh schedules table. Existing schedule rows are not migrated.
        if "name" not in columns:
            conn.execute("DROP INDEX IF EXISTS idx_schedules_due_status")
            conn.execute("DROP INDEX IF EXISTS idx_schedules_thread")
            legacy_name = f"schedules_legacy_{int(time.time())}"
            conn.execute(f"ALTER TABLE schedules RENAME TO {legacy_name}")
            conn.execute(
                """
                CREATE TABLE schedules (
                    schedule_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    run_at REAL,
                    cron TEXT,
                    timezone TEXT,
                    next_run_at REAL NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    protected INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    lease_expires_at REAL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    last_run_at REAL,
                    state_json TEXT,
                    state_version INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(session_id, thread_id, name)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX idx_schedules_due_status
                ON schedules(status, enabled, next_run_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX idx_schedules_thread
                ON schedules(session_id, thread_id, updated_at)
                """
            )
            return

        # Forward-compatible column additions (best-effort).
        if "trigger_type" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN trigger_type TEXT NOT NULL DEFAULT 'once'")
        if "run_at" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN run_at REAL")
        if "cron" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN cron TEXT")
        if "timezone" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN timezone TEXT")
        if "next_run_at" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN next_run_at REAL NOT NULL DEFAULT 0")
        if "enabled" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1")
        if "protected" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN protected INTEGER NOT NULL DEFAULT 0")
        if "state_json" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN state_json TEXT")
        if "state_version" not in columns:
            conn.execute("ALTER TABLE schedules ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0")

    @staticmethod
    def _column_exists(conn: sqlite3.Connection, *, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        for row in rows:
            if len(row) >= 2 and row[1] == column:
                return True
        return False

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, Sequence

from pydantic_ai.messages import ModelMessage

WorkspaceKind = Literal["global", "project"]
ThreadStatus = Literal["idle", "running", "waiting_approval"]
RunStatus = Literal["running", "waiting_approval", "completed", "cancelled", "failed"]
ItemKind = Literal[
    "user_message",
    "assistant_text",
    "reasoning",
    "tool_call",
    "approval_request",
    "system_note",
]
ItemStatus = Literal["streaming", "completed", "error", "cancelled"]

GLOBAL_WORKSPACE_ID = "global"


def generate_workspace_id() -> str:
    return f"ws-{uuid.uuid4().hex[:8]}"


def generate_thread_id(prefix: str = "thr") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def generate_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:8]}"


def generate_item_id() -> str:
    return f"itm-{uuid.uuid4().hex[:8]}"


def generate_approval_id() -> str:
    return f"apr-{uuid.uuid4().hex[:8]}"


@dataclass
class WorkspaceRecord:
    id: str
    name: str
    root_path: str
    kind: WorkspaceKind
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class ThreadRecord:
    id: str
    workspace_id: str
    title: str
    agent_id: str | None
    model: str | None
    status: ThreadStatus
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0


@dataclass
class RunRecord:
    id: str
    thread_id: str
    workspace_id: str
    agent_id: str
    model: str
    status: RunStatus
    usage: dict[str, Any] | None = None
    error: str | None = None
    started_at: float = 0.0
    ended_at: float | None = None


@dataclass
class ItemRecord:
    id: str
    thread_id: str
    run_id: str | None
    seq: int
    kind: ItemKind
    status: ItemStatus
    payload: dict[str, Any]
    created_at: float = 0.0
    updated_at: float = 0.0


class DaemonStore(Protocol):
    # Workspaces
    def ensure_global_workspace(self, root_path: str) -> WorkspaceRecord: ...
    def list_workspaces(self) -> list[WorkspaceRecord]: ...
    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None: ...
    def get_workspace_by_path(self, root_path: str) -> WorkspaceRecord | None: ...
    def upsert_workspace(
        self,
        *,
        root_path: str,
        name: str,
        kind: WorkspaceKind = "project",
        workspace_id: str | None = None,
    ) -> tuple[WorkspaceRecord, bool]: ...
    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> WorkspaceRecord: ...
    def delete_workspace(self, workspace_id: str) -> None: ...
    def count_workspace_threads(self, workspace_id: str) -> int: ...

    # Threads
    def list_threads(self, workspace_id: str) -> list[ThreadRecord]: ...
    def get_thread(self, thread_id: str) -> ThreadRecord | None: ...
    def create_thread(
        self,
        *,
        workspace_id: str,
        thread_id: str | None = None,
        title: str = "",
        agent_id: str | None = None,
        model: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ThreadRecord: ...
    def update_thread(
        self,
        thread_id: str,
        *,
        title: str | None = None,
        agent_id: str | None | object = ...,
        model: str | None | object = ...,
        status: ThreadStatus | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ThreadRecord: ...
    def delete_thread(self, thread_id: str) -> None: ...
    def clear_thread(self, thread_id: str) -> None: ...
    def load_model_messages(self, thread_id: str) -> list[ModelMessage]: ...
    def save_model_messages(self, thread_id: str, messages: Sequence[ModelMessage]) -> None: ...

    # Runs
    def create_run(
        self,
        *,
        run_id: str,
        thread_id: str,
        workspace_id: str,
        agent_id: str,
        model: str,
        status: RunStatus = "running",
    ) -> RunRecord: ...
    def get_run(self, run_id: str) -> RunRecord | None: ...
    def list_runs(self, thread_id: str, *, limit: int = 50) -> list[RunRecord]: ...
    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
        ended_at: float | None = None,
    ) -> RunRecord: ...
    def recover_interrupted_runs(self) -> int: ...

    # Items
    def append_item(
        self,
        *,
        thread_id: str,
        run_id: str | None,
        kind: ItemKind,
        status: ItemStatus,
        payload: dict[str, Any],
        item_id: str | None = None,
    ) -> ItemRecord: ...
    def update_item(
        self,
        item_id: str,
        *,
        status: ItemStatus | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ItemRecord: ...
    def get_item(self, item_id: str) -> ItemRecord | None: ...
    def list_items(
        self,
        thread_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> tuple[list[ItemRecord], bool]: ...

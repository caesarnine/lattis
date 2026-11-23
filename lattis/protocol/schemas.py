from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from lattis.domain.models import (
    ItemKind,
    ItemRecord,
    ItemStatus,
    RunRecord,
    RunStatus,
    ThreadRecord,
    ThreadStatus,
    WorkspaceKind,
    WorkspaceRecord,
)

# ---------------------------------------------------------------------------
# System / Meta / Agents
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ServerInfoResponse(BaseModel):
    version: str
    pid: int
    lattis_home: str
    default_agent: str
    active_runs: int = 0
    auth_enabled: bool = True


class AgentInfo(BaseModel):
    id: str
    name: str
    default_model: str | None = None
    has_state: bool = False


class AgentListResponse(BaseModel):
    default_agent: str
    agents: list[AgentInfo]


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


class WorkspaceCreateRequest(BaseModel):
    root_path: str
    name: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    settings: dict[str, Any] | None = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    root_path: str
    kind: WorkspaceKind
    settings: dict[str, Any] = Field(default_factory=dict)
    thread_count: int = 0
    created_at: float
    updated_at: float

    @classmethod
    def from_record(cls, record: WorkspaceRecord, *, thread_count: int = 0) -> WorkspaceResponse:
        return cls(
            id=record.id,
            name=record.name,
            root_path=record.root_path,
            kind=record.kind,
            settings=record.settings,
            thread_count=thread_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]


class WorkspaceDeleteResponse(BaseModel):
    deleted: str


# ---------------------------------------------------------------------------
# Workspace Files & Git Inspection
# ---------------------------------------------------------------------------


class FileEntryResponse(BaseModel):
    name: str
    path: str
    kind: Literal["dir", "file"]
    size: int | None = None
    mtime: float | None = None


class WorkspaceFilesResponse(BaseModel):
    workspace_id: str
    path: str
    entries: list[FileEntryResponse]


class WorkspaceFileReadResponse(BaseModel):
    workspace_id: str
    path: str
    content: str
    size: int
    is_binary: bool = False
    truncated: bool = False


class GitFileStatusResponse(BaseModel):
    path: str
    index_status: str
    worktree_status: str
    status: Literal["modified", "added", "deleted", "renamed", "untracked", "conflicted"]


class GitStatusResponse(BaseModel):
    workspace_id: str
    is_git_repo: bool
    branch: str | None = None
    ahead: int = 0
    behind: int = 0
    files: list[GitFileStatusResponse] = Field(default_factory=list)


class GitDiffResponse(BaseModel):
    workspace_id: str
    is_git_repo: bool
    path: str | None = None
    staged: bool = False
    diff: str = ""
    truncated: bool = False


# ---------------------------------------------------------------------------
# Threads & Models
# ---------------------------------------------------------------------------


class ThreadAgentResponse(BaseModel):
    agent: str
    default_agent: str
    is_default: bool
    agent_name: str


class ThreadModelResponse(BaseModel):
    model: str
    default_model: str
    is_default: bool


class ModelListResponse(BaseModel):
    default_model: str
    models: list[str]


class ThreadCreateRequest(BaseModel):
    thread_id: str | None = None
    title: str = ""
    agent_id: str | None = None
    model: str | None = None
    settings: dict[str, Any] | None = None


class ThreadUpdateRequest(BaseModel):
    title: str | None = None
    agent_id: str | None = None
    model: str | None = None
    settings: dict[str, Any] | None = None


class ThreadResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    agent_id: str | None = None
    model: str | None = None
    resolved_agent: ThreadAgentResponse
    resolved_model: ThreadModelResponse
    status: ThreadStatus
    settings: dict[str, Any] = Field(default_factory=dict)
    active_run_id: str | None = None
    created_at: float
    updated_at: float

    @classmethod
    def from_record(
        cls,
        record: ThreadRecord,
        *,
        resolved_agent: ThreadAgentResponse,
        resolved_model: ThreadModelResponse,
        active_run_id: str | None = None,
    ) -> ThreadResponse:
        return cls(
            id=record.id,
            workspace_id=record.workspace_id,
            title=record.title,
            agent_id=record.agent_id,
            model=record.model,
            resolved_agent=resolved_agent,
            resolved_model=resolved_model,
            status=record.status,
            settings=record.settings,
            active_run_id=active_run_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class ThreadListResponse(BaseModel):
    threads: list[ThreadResponse]


class ThreadDeleteResponse(BaseModel):
    deleted: str


class ThreadClearResponse(BaseModel):
    cleared: str


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


class ItemResponse(BaseModel):
    id: str
    thread_id: str
    run_id: str | None = None
    seq: int
    kind: ItemKind
    status: ItemStatus
    payload: dict[str, Any]
    created_at: float
    updated_at: float

    @classmethod
    def from_record(cls, record: ItemRecord) -> ItemResponse:
        return cls(
            id=record.id,
            thread_id=record.thread_id,
            run_id=record.run_id,
            seq=record.seq,
            kind=record.kind,
            status=record.status,
            payload=record.payload,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class ItemListResponse(BaseModel):
    items: list[ItemResponse]
    has_more: bool = False


# ---------------------------------------------------------------------------
# Runs & Approvals
# ---------------------------------------------------------------------------


class RunResponse(BaseModel):
    id: str
    thread_id: str
    workspace_id: str
    agent_id: str
    model: str
    status: RunStatus
    usage: dict[str, Any] | None = None
    error: str | None = None
    started_at: float
    ended_at: float | None = None

    @classmethod
    def from_record(cls, record: RunRecord) -> RunResponse:
        return cls(
            id=record.id,
            thread_id=record.thread_id,
            workspace_id=record.workspace_id,
            agent_id=record.agent_id,
            model=record.model,
            status=record.status,
            usage=record.usage,
            error=record.error,
            started_at=record.started_at,
            ended_at=record.ended_at,
        )


class RunCreateRequest(BaseModel):
    input: str = Field(min_length=1)


class RunCreateResponse(BaseModel):
    run: RunResponse
    user_item: ItemResponse


class RunListResponse(BaseModel):
    runs: list[RunResponse]


class ApprovalResolveRequest(BaseModel):
    approved: bool
    reason: str | None = None


class ApprovalResolveResponse(BaseModel):
    run: RunResponse
    approval_item: ItemResponse


# ---------------------------------------------------------------------------
# Plugins
# ---------------------------------------------------------------------------


class PluginStateResponse(BaseModel):
    workspace_id: str
    agent_id: str
    state: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# SSE Event Bus (Discriminated Union)
# ---------------------------------------------------------------------------


class _BaseEvent(BaseModel):
    seq: int
    timestamp: float
    workspace_id: str | None = None
    thread_id: str | None = None
    run_id: str | None = None


class ResyncRequiredData(BaseModel):
    reason: str
    earliest_seq: int | None = None
    latest_seq: int


class BusResyncRequiredEvent(_BaseEvent):
    type: Literal["bus.resync_required"] = "bus.resync_required"
    data: ResyncRequiredData


class WorkspaceCreatedEvent(_BaseEvent):
    type: Literal["workspace.created"] = "workspace.created"
    data: WorkspaceResponse


class WorkspaceUpdatedEvent(_BaseEvent):
    type: Literal["workspace.updated"] = "workspace.updated"
    data: WorkspaceResponse


class WorkspaceDeletedData(BaseModel):
    workspace_id: str


class WorkspaceDeletedEvent(_BaseEvent):
    type: Literal["workspace.deleted"] = "workspace.deleted"
    data: WorkspaceDeletedData


class ThreadCreatedEvent(_BaseEvent):
    type: Literal["thread.created"] = "thread.created"
    data: ThreadResponse


class ThreadUpdatedEvent(_BaseEvent):
    type: Literal["thread.updated"] = "thread.updated"
    data: ThreadResponse


class ThreadIdData(BaseModel):
    thread_id: str


class ThreadDeletedEvent(_BaseEvent):
    type: Literal["thread.deleted"] = "thread.deleted"
    data: ThreadIdData


class ThreadClearedEvent(_BaseEvent):
    type: Literal["thread.cleared"] = "thread.cleared"
    data: ThreadIdData


class RunStartedEvent(_BaseEvent):
    type: Literal["run.started"] = "run.started"
    data: RunResponse


class RunWaitingApprovalData(BaseModel):
    run: RunResponse
    approval_items: list[ItemResponse]


class RunWaitingApprovalEvent(_BaseEvent):
    type: Literal["run.waiting_approval"] = "run.waiting_approval"
    data: RunWaitingApprovalData


class RunCompletedEvent(_BaseEvent):
    type: Literal["run.completed"] = "run.completed"
    data: RunResponse


class RunCancelledEvent(_BaseEvent):
    type: Literal["run.cancelled"] = "run.cancelled"
    data: RunResponse


class RunFailedEvent(_BaseEvent):
    type: Literal["run.failed"] = "run.failed"
    data: RunResponse


class ItemCreatedEvent(_BaseEvent):
    type: Literal["item.created"] = "item.created"
    data: ItemResponse


DeltaChannel = Literal["text", "reasoning", "tool_input", "tool_output"]


class ItemDeltaData(BaseModel):
    item_id: str
    channel: DeltaChannel
    delta: str
    stream: Literal["stdout", "stderr"] | None = None


class ItemDeltaEvent(_BaseEvent):
    type: Literal["item.delta"] = "item.delta"
    data: ItemDeltaData


class ItemCompletedEvent(_BaseEvent):
    type: Literal["item.completed"] = "item.completed"
    data: ItemResponse


class PluginStateUpdatedEvent(_BaseEvent):
    type: Literal["plugin.state_updated"] = "plugin.state_updated"
    data: PluginStateResponse


LattisEvent = Annotated[
    Union[
        BusResyncRequiredEvent,
        WorkspaceCreatedEvent,
        WorkspaceUpdatedEvent,
        WorkspaceDeletedEvent,
        ThreadCreatedEvent,
        ThreadUpdatedEvent,
        ThreadDeletedEvent,
        ThreadClearedEvent,
        RunStartedEvent,
        RunWaitingApprovalEvent,
        RunCompletedEvent,
        RunCancelledEvent,
        RunFailedEvent,
        ItemCreatedEvent,
        ItemDeltaEvent,
        ItemCompletedEvent,
        PluginStateUpdatedEvent,
    ],
    Field(discriminator="type"),
]


class EventSchemaEnvelope(BaseModel):
    """Wrapper schema used to export the full LattisEvent union into OpenAPI."""

    event: LattisEvent

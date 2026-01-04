from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic_ai.ui.vercel_ai.request_types import UIMessage


class ThreadCreateRequest(BaseModel):
    thread_id: str | None = None


class ThreadCreateResponse(BaseModel):
    thread_id: str


class ThreadDeleteResponse(BaseModel):
    deleted: str


class ThreadClearResponse(BaseModel):
    cleared: str


class ThreadListResponse(BaseModel):
    threads: list[str]

class ModelListResponse(BaseModel):
    default_model: str
    models: list[str]


class AgentInfo(BaseModel):
    id: str
    name: str


class AgentListResponse(BaseModel):
    default_agent: str
    agents: list[AgentInfo]


class ThreadAgentResponse(BaseModel):
    agent: str
    default_agent: str
    is_default: bool
    agent_name: str | None = None


class SessionModelResponse(BaseModel):
    model: str
    default_model: str
    is_default: bool


class ThreadStateUpdateRequest(BaseModel):
    agent: str | None = None
    model: str | None = None


class ThreadStateResponse(BaseModel):
    thread_id: str
    agent: ThreadAgentResponse
    model: SessionModelResponse
    messages: list[UIMessage]


class SessionBootstrapResponse(BaseModel):
    session_id: str
    thread_id: str
    threads: list[str]
    agent: ThreadAgentResponse
    model: SessionModelResponse
    messages: list[UIMessage]


class ServerInfoResponse(BaseModel):
    version: str
    pid: int
    project_root: str
    data_dir: str
    workspace_dir: str
    workspace_mode: Literal["central", "local"]
    agent_name: str | None = None

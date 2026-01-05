from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, Sequence

from pydantic import BaseModel, ConfigDict

from pydantic_ai.messages import ModelMessage


@dataclass
class ThreadState:
    session_id: str
    thread_id: str
    messages: list[ModelMessage]


class ThreadSettings(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent: str | None = None


class SessionStore(Protocol):
    def load_thread(
        self,
        session_id: str,
        thread_id: str,
    ) -> ThreadState | None: ...

    def save_thread(
        self,
        session_id: str,
        thread_id: str,
        *,
        messages: Sequence[ModelMessage],
    ) -> None: ...

    def list_threads(self, session_id: str) -> list[str]: ...

    def thread_exists(self, session_id: str, thread_id: str) -> bool: ...

    def list_sessions(self) -> list[str]: ...

    def delete_thread(self, session_id: str, thread_id: str) -> None: ...

    def get_session_model(self, session_id: str) -> str | None: ...

    def set_session_model(self, session_id: str, model: str | None) -> None: ...

    def get_thread_settings(self, session_id: str, thread_id: str) -> ThreadSettings: ...

    def set_thread_settings(self, session_id: str, thread_id: str, settings: ThreadSettings) -> None: ...


def generate_thread_id(prefix: str = "thread") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

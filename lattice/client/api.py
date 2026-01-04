from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
from pydantic_ai.ui.vercel_ai.request_types import RequestData

from lattice.client.streaming import iter_ui_events
from lattice.protocol.models import (
    AgentListResponse,
    ModelListResponse,
    ServerInfoResponse,
    ThreadAgentRequest,
    ThreadAgentResponse,
    SessionModelRequest,
    SessionModelResponse,
    ThreadClearResponse,
    ThreadCreateRequest,
    ThreadCreateResponse,
    ThreadDeleteResponse,
    ThreadListResponse,
    ThreadMessagesResponse,
)


class AgentClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float | None = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    @staticmethod
    def _format_error_message(fallback: str, detail: str) -> str:
        return f"{fallback}. {detail}" if detail else fallback

    def _extract_detail(self, response: httpx.Response, *, body: bytes | None = None) -> str:
        data: object | None = None
        if body is None:
            try:
                data = response.json()
            except Exception:
                data = None
        else:
            try:
                data = json.loads(body)
            except Exception:
                data = None
        if isinstance(data, dict) and data.get("detail"):
            return str(data["detail"])

        if body is None:
            try:
                text = response.text
                if text:
                    return text.strip()
            except Exception:
                return ""
        else:
            try:
                text = body.decode("utf-8", errors="ignore").strip()
                if text:
                    return text
            except Exception:
                return ""
        return ""

    def _raise_for_status(self, response: httpx.Response, fallback: str) -> None:
        try:
            response.raise_for_status()
            return
        except httpx.HTTPStatusError as exc:
            detail = self._extract_detail(response)
            message = self._format_error_message(fallback, detail)
            raise RuntimeError(message) from exc

    async def _raise_for_status_async(self, response: httpx.Response, fallback: str) -> None:
        if response.status_code < 400:
            return
        body: bytes | None = None
        try:
            body = await response.aread()
        except Exception:
            body = None
        detail = self._extract_detail(response, body=body)
        message = self._format_error_message(fallback, detail)
        raise RuntimeError(message)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_session_id(self) -> str:
        response = await self._client.get("/session")
        self._raise_for_status(response, "Failed to load session")
        data = response.json()
        session_id = data.get("session_id") or data.get("sessionId")
        if not session_id:
            raise ValueError("Server did not return a session id.")
        return session_id

    async def get_server_info(self) -> ServerInfoResponse:
        response = await self._client.get("/info")
        self._raise_for_status(response, "Failed to load server info")
        return ServerInfoResponse.model_validate(response.json())

    async def list_models(self) -> ModelListResponse:
        response = await self._client.get("/models")
        self._raise_for_status(response, "Failed to load models")
        return ModelListResponse.model_validate(response.json())

    async def list_agents(self) -> AgentListResponse:
        response = await self._client.get("/agents")
        self._raise_for_status(response, "Failed to load agents")
        return AgentListResponse.model_validate(response.json())

    async def get_thread_agent(self, session_id: str, thread_id: str) -> ThreadAgentResponse:
        response = await self._client.get(f"/sessions/{session_id}/threads/{thread_id}/agent")
        self._raise_for_status(response, "Failed to load agent")
        return ThreadAgentResponse.model_validate(response.json())

    async def set_thread_agent(self, session_id: str, thread_id: str, agent: str | None) -> ThreadAgentResponse:
        payload = ThreadAgentRequest(agent=agent)
        response = await self._client.put(
            f"/sessions/{session_id}/threads/{thread_id}/agent",
            json=payload.model_dump(mode="json", exclude_none=True),
        )
        self._raise_for_status(response, "Failed to set agent")
        return ThreadAgentResponse.model_validate(response.json())

    async def get_session_model(self, session_id: str) -> SessionModelResponse:
        response = await self._client.get(f"/sessions/{session_id}/model")
        self._raise_for_status(response, "Failed to load model")
        return SessionModelResponse.model_validate(response.json())

    async def set_session_model(self, session_id: str, model: str | None) -> SessionModelResponse:
        payload = SessionModelRequest(model=model)
        response = await self._client.put(
            f"/sessions/{session_id}/model",
            json=payload.model_dump(mode="json", exclude_none=True),
        )
        self._raise_for_status(response, "Failed to set model")
        return SessionModelResponse.model_validate(response.json())

    async def list_threads(self, session_id: str) -> list[str]:
        response = await self._client.get(f"/sessions/{session_id}/threads")
        self._raise_for_status(response, "Failed to load threads")
        payload = ThreadListResponse.model_validate(response.json())
        return payload.threads

    async def create_thread(self, session_id: str, thread_id: str | None = None) -> str:
        payload = ThreadCreateRequest(thread_id=thread_id)
        response = await self._client.post(
            f"/sessions/{session_id}/threads",
            json=payload.model_dump(mode="json", exclude_none=True),
        )
        self._raise_for_status(response, "Failed to create thread")
        data = ThreadCreateResponse.model_validate(response.json())
        return data.thread_id

    async def delete_thread(self, session_id: str, thread_id: str) -> str:
        response = await self._client.delete(f"/sessions/{session_id}/threads/{thread_id}")
        self._raise_for_status(response, "Failed to delete thread")
        data = ThreadDeleteResponse.model_validate(response.json())
        return data.deleted

    async def clear_thread(self, session_id: str, thread_id: str) -> str:
        response = await self._client.post(f"/sessions/{session_id}/threads/{thread_id}/clear")
        self._raise_for_status(response, "Failed to clear thread")
        data = ThreadClearResponse.model_validate(response.json())
        return data.cleared

    async def get_thread_messages(self, session_id: str, thread_id: str) -> ThreadMessagesResponse:
        response = await self._client.get(f"/sessions/{session_id}/threads/{thread_id}/messages")
        self._raise_for_status(response, "Failed to load messages")
        return ThreadMessagesResponse.model_validate(response.json())

    async def run_stream(self, run_input: RequestData) -> AsyncIterator[dict]:
        payload = run_input.model_dump(mode="json", by_alias=True, exclude_none=True)
        headers = {"accept": "text/event-stream"}
        async with self._client.stream("POST", "/ui/chat", json=payload, headers=headers) as response:
            await self._raise_for_status_async(response, "Failed to run agent")
            async for event in iter_ui_events(response.aiter_lines()):
                yield event

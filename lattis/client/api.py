from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from lattis.client.streaming import iter_sse_events
from lattis.protocol.schemas import (
    AgentListResponse,
    ApprovalResolveRequest,
    ApprovalResolveResponse,
    GitDiffResponse,
    GitStatusResponse,
    HealthResponse,
    ItemListResponse,
    LattisEvent,
    ModelListResponse,
    PluginStateResponse,
    RunCreateRequest,
    RunCreateResponse,
    RunListResponse,
    RunResponse,
    ServerInfoResponse,
    ThreadClearResponse,
    ThreadCreateRequest,
    ThreadDeleteResponse,
    ThreadListResponse,
    ThreadResponse,
    WorkspaceCreateRequest,
    WorkspaceDeleteResponse,
    WorkspaceFileReadResponse,
    WorkspaceFilesResponse,
    WorkspaceListResponse,
    WorkspaceResponse,
)

_UNSET = object()


class AgentClient:
    """Async HTTP + SSE client for the Lattis v2 daemon."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float | None = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers=headers,
        )
        if client is not None and token:
            self._client.headers["Authorization"] = f"Bearer {token}"

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

    async def __aenter__(self) -> AgentClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # System / Agents
    # ------------------------------------------------------------------

    async def health(self) -> HealthResponse:
        response = await self._client.get("/health")
        self._raise_for_status(response, "Health check failed")
        return HealthResponse.model_validate(response.json())

    async def get_server_info(self) -> ServerInfoResponse:
        response = await self._client.get("/info")
        self._raise_for_status(response, "Failed to load server info")
        return ServerInfoResponse.model_validate(response.json())

    async def list_agents(self) -> AgentListResponse:
        response = await self._client.get("/agents")
        self._raise_for_status(response, "Failed to load agents")
        return AgentListResponse.model_validate(response.json())

    # ------------------------------------------------------------------
    # Workspaces
    # ------------------------------------------------------------------

    async def list_workspaces(self) -> list[WorkspaceResponse]:
        response = await self._client.get("/workspaces")
        self._raise_for_status(response, "Failed to load workspaces")
        return WorkspaceListResponse.model_validate(response.json()).workspaces

    async def register_workspace(self, root_path: str, *, name: str | None = None) -> WorkspaceResponse:
        payload = WorkspaceCreateRequest(root_path=root_path, name=name)
        response = await self._client.post(
            "/workspaces",
            json=payload.model_dump(mode="json", exclude_none=True),
        )
        self._raise_for_status(response, "Failed to register workspace")
        return WorkspaceResponse.model_validate(response.json())

    async def get_workspace(self, workspace_id: str) -> WorkspaceResponse:
        response = await self._client.get(f"/workspaces/{workspace_id}")
        self._raise_for_status(response, "Failed to load workspace")
        return WorkspaceResponse.model_validate(response.json())

    async def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None | object = _UNSET,
        settings: dict[str, Any] | object = _UNSET,
    ) -> WorkspaceResponse:
        payload: dict[str, Any] = {}
        if name is not _UNSET:
            payload["name"] = name
        if settings is not _UNSET:
            payload["settings"] = settings
        response = await self._client.patch(f"/workspaces/{workspace_id}", json=payload)
        self._raise_for_status(response, "Failed to update workspace")
        return WorkspaceResponse.model_validate(response.json())

    async def delete_workspace(self, workspace_id: str) -> str:
        response = await self._client.delete(f"/workspaces/{workspace_id}")
        self._raise_for_status(response, "Failed to delete workspace")
        return WorkspaceDeleteResponse.model_validate(response.json()).deleted

    # ------------------------------------------------------------------
    # Workspace Files & Git Inspection
    # ------------------------------------------------------------------

    async def list_workspace_files(
        self,
        workspace_id: str,
        *,
        path: str = "",
        include_hidden: bool = False,
    ) -> WorkspaceFilesResponse:
        params: dict[str, Any] = {"include_hidden": include_hidden}
        if path:
            params["path"] = path
        response = await self._client.get(f"/workspaces/{workspace_id}/files", params=params)
        self._raise_for_status(response, "Failed to list workspace files")
        return WorkspaceFilesResponse.model_validate(response.json())

    async def read_workspace_file(
        self,
        workspace_id: str,
        path: str,
        *,
        max_bytes: int | None = None,
    ) -> WorkspaceFileReadResponse:
        params: dict[str, Any] = {"path": path}
        if max_bytes is not None:
            params["max_bytes"] = max_bytes
        response = await self._client.get(f"/workspaces/{workspace_id}/file", params=params)
        self._raise_for_status(response, "Failed to read workspace file")
        return WorkspaceFileReadResponse.model_validate(response.json())

    async def get_git_status(self, workspace_id: str) -> GitStatusResponse:
        response = await self._client.get(f"/workspaces/{workspace_id}/git/status")
        self._raise_for_status(response, "Failed to load git status")
        return GitStatusResponse.model_validate(response.json())

    async def get_git_diff(
        self,
        workspace_id: str,
        *,
        path: str | None = None,
        staged: bool = False,
    ) -> GitDiffResponse:
        params: dict[str, Any] = {"staged": staged}
        if path:
            params["path"] = path
        response = await self._client.get(f"/workspaces/{workspace_id}/git/diff", params=params)
        self._raise_for_status(response, "Failed to load git diff")
        return GitDiffResponse.model_validate(response.json())

    # ------------------------------------------------------------------
    # Threads & Items
    # ------------------------------------------------------------------

    async def list_threads(self, workspace_id: str) -> list[ThreadResponse]:
        response = await self._client.get(f"/workspaces/{workspace_id}/threads")
        self._raise_for_status(response, "Failed to load threads")
        return ThreadListResponse.model_validate(response.json()).threads

    async def create_thread(
        self,
        workspace_id: str,
        *,
        thread_id: str | None = None,
        title: str = "",
        agent_id: str | None = None,
        model: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> ThreadResponse:
        payload = ThreadCreateRequest(
            thread_id=thread_id,
            title=title,
            agent_id=agent_id,
            model=model,
            settings=settings,
        )
        response = await self._client.post(
            f"/workspaces/{workspace_id}/threads",
            json=payload.model_dump(mode="json", exclude_none=True),
        )
        self._raise_for_status(response, "Failed to create thread")
        return ThreadResponse.model_validate(response.json())

    async def get_thread(self, thread_id: str) -> ThreadResponse:
        response = await self._client.get(f"/threads/{thread_id}")
        self._raise_for_status(response, "Failed to load thread")
        return ThreadResponse.model_validate(response.json())

    async def update_thread(
        self,
        thread_id: str,
        *,
        title: str | object = _UNSET,
        agent_id: str | None | object = _UNSET,
        model: str | None | object = _UNSET,
        settings: dict[str, Any] | object = _UNSET,
    ) -> ThreadResponse:
        payload: dict[str, Any] = {}
        if title is not _UNSET:
            payload["title"] = title
        if agent_id is not _UNSET:
            payload["agent_id"] = agent_id
        if model is not _UNSET:
            payload["model"] = model
        if settings is not _UNSET:
            payload["settings"] = settings
        response = await self._client.patch(f"/threads/{thread_id}", json=payload)
        self._raise_for_status(response, "Failed to update thread")
        return ThreadResponse.model_validate(response.json())

    async def delete_thread(self, thread_id: str) -> str:
        response = await self._client.delete(f"/threads/{thread_id}")
        self._raise_for_status(response, "Failed to delete thread")
        return ThreadDeleteResponse.model_validate(response.json()).deleted

    async def clear_thread(self, thread_id: str) -> str:
        response = await self._client.post(f"/threads/{thread_id}/clear")
        self._raise_for_status(response, "Failed to clear thread")
        return ThreadClearResponse.model_validate(response.json()).cleared

    async def list_thread_models(self, thread_id: str) -> ModelListResponse:
        response = await self._client.get(f"/threads/{thread_id}/models")
        self._raise_for_status(response, "Failed to load models")
        return ModelListResponse.model_validate(response.json())

    async def list_thread_items(
        self,
        thread_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> ItemListResponse:
        response = await self._client.get(
            f"/threads/{thread_id}/items",
            params={"after_seq": after_seq, "limit": limit},
        )
        self._raise_for_status(response, "Failed to load thread items")
        return ItemListResponse.model_validate(response.json())

    # ------------------------------------------------------------------
    # Runs & Approvals
    # ------------------------------------------------------------------

    async def start_run(self, thread_id: str, user_input: str) -> RunCreateResponse:
        payload = RunCreateRequest(input=user_input)
        response = await self._client.post(
            f"/threads/{thread_id}/runs",
            json=payload.model_dump(mode="json"),
        )
        self._raise_for_status(response, "Failed to start run")
        return RunCreateResponse.model_validate(response.json())

    async def list_runs(self, thread_id: str, *, limit: int = 50) -> list[RunResponse]:
        response = await self._client.get(f"/threads/{thread_id}/runs", params={"limit": limit})
        self._raise_for_status(response, "Failed to load runs")
        return RunListResponse.model_validate(response.json()).runs

    async def get_run(self, run_id: str) -> RunResponse:
        response = await self._client.get(f"/runs/{run_id}")
        self._raise_for_status(response, "Failed to load run")
        return RunResponse.model_validate(response.json())

    async def cancel_run(self, run_id: str) -> RunResponse:
        response = await self._client.post(f"/runs/{run_id}/cancel")
        self._raise_for_status(response, "Failed to cancel run")
        return RunResponse.model_validate(response.json())

    async def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        *,
        approved: bool,
        reason: str | None = None,
    ) -> ApprovalResolveResponse:
        payload = ApprovalResolveRequest(approved=approved, reason=reason)
        response = await self._client.post(
            f"/runs/{run_id}/approvals/{approval_id}",
            json=payload.model_dump(mode="json", exclude_none=True),
        )
        self._raise_for_status(response, "Failed to resolve approval")
        return ApprovalResolveResponse.model_validate(response.json())

    # ------------------------------------------------------------------
    # Plugins & Events
    # ------------------------------------------------------------------

    async def get_plugin_state(self, workspace_id: str, agent_id: str) -> PluginStateResponse:
        response = await self._client.get(f"/workspaces/{workspace_id}/plugins/{agent_id}/state")
        self._raise_for_status(response, "Failed to load plugin state")
        return PluginStateResponse.model_validate(response.json())

    async def iter_events(
        self,
        *,
        workspace_id: str | None = None,
        thread_id: str | None = None,
        after_seq: int | None = None,
    ) -> AsyncIterator[LattisEvent]:
        params: dict[str, Any] = {}
        if workspace_id is not None:
            params["workspace_id"] = workspace_id
        if thread_id is not None:
            params["thread_id"] = thread_id
        if after_seq is not None:
            params["after_seq"] = after_seq

        headers = {"Accept": "text/event-stream"}
        async with self._client.stream(
            "GET",
            "/events",
            params=params,
            headers=headers,
            timeout=None,
        ) as response:
            await self._raise_for_status_async(response, "Failed to subscribe to event stream")
            async for event in iter_sse_events(response.aiter_lines()):
                yield event

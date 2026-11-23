import type { components } from "@/generated/openapi";

export type ServerInfo = components["schemas"]["ServerInfoResponse"];
export type AgentInfo = components["schemas"]["AgentInfo"];
export type Workspace = components["schemas"]["WorkspaceResponse"];
export type FileEntry = components["schemas"]["FileEntryResponse"];
export type WorkspaceFiles = components["schemas"]["WorkspaceFilesResponse"];
export type WorkspaceFileRead = components["schemas"]["WorkspaceFileReadResponse"];
export type GitFileStatus = components["schemas"]["GitFileStatusResponse"];
export type GitStatus = components["schemas"]["GitStatusResponse"];
export type GitDiff = components["schemas"]["GitDiffResponse"];
export type Thread = components["schemas"]["ThreadResponse"];
export type Item = components["schemas"]["ItemResponse"];
export type Run = components["schemas"]["RunResponse"];
export type RunCreateResult = components["schemas"]["RunCreateResponse"];
export type ApprovalResolveResult = components["schemas"]["ApprovalResolveResponse"];
export type PluginState = components["schemas"]["PluginStateResponse"];
export type LattisEvent = components["schemas"]["EventSchemaEnvelope"]["event"];

const TOKEN_STORAGE_KEY = "lattis_api_token";

function resolveDefaultServerUrl(): string {
  const envUrl = import.meta.env.VITE_LATTIS_SERVER_URL as string | undefined;
  if (envUrl && envUrl.trim()) {
    return envUrl.trim().replace(/\/+$/, "");
  }
  if (typeof window !== "undefined" && window.location?.origin) {
    return window.location.origin;
  }
  return "http://127.0.0.1:7700";
}

export const SERVER_URL = resolveDefaultServerUrl();

export class UnauthorizedError extends Error {
  constructor(message = "Authentication required.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export function getAuthToken(): string | null {
  if (typeof window !== "undefined") {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("token");
    if (urlToken && urlToken.trim()) {
      const cleaned = urlToken.trim();
      window.localStorage.setItem(TOKEN_STORAGE_KEY, cleaned);
      params.delete("token");
      const nextSearch = params.toString();
      const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ""}${window.location.hash}`;
      window.history.replaceState({}, "", nextUrl);
      return cleaned;
    }
    const stored = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (stored && stored.trim()) {
      return stored.trim();
    }
  }
  const envToken = import.meta.env.VITE_LATTIS_API_TOKEN as string | undefined;
  return envToken && envToken.trim() ? envToken.trim() : null;
}

export function setAuthToken(token: string | null): void {
  if (typeof window === "undefined") return;
  const trimmed = token?.trim() ?? "";
  if (trimmed) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, trimmed);
  } else {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

type RequestJsonOptions = Omit<RequestInit, "body"> & { body?: unknown };

function buildUrl(path: string): string {
  return new URL(path, `${SERVER_URL}/`).toString();
}

function buildAuthHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  const token = getAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function getErrorDetail(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === "string" && data.detail) {
      return data.detail;
    }
  } catch {
    // ignore JSON errors
  }
  return "";
}

async function request(path: string, fallbackMessage: string, options: RequestInit = {}): Promise<Response> {
  const headers = buildAuthHeaders(options.headers);
  const response = await fetch(buildUrl(path), {
    ...options,
    headers
  });
  if (response.ok) {
    return response;
  }
  const detail = await getErrorDetail(response);
  if (response.status === 401) {
    throw new UnauthorizedError(detail || "Invalid or missing authentication token.");
  }
  throw new Error(detail ? `${fallbackMessage}. ${detail}` : fallbackMessage);
}

async function requestJson<T>(
  path: string,
  fallbackMessage: string,
  options: RequestJsonOptions = {}
): Promise<T> {
  const { body, headers, ...rest } = options;
  const finalHeaders = buildAuthHeaders(headers);
  if (body !== undefined && !finalHeaders.has("Content-Type")) {
    finalHeaders.set("Content-Type", "application/json");
  }
  const response = await request(path, fallbackMessage, {
    ...rest,
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// REST API
// ---------------------------------------------------------------------------

export async function getServerInfo(): Promise<ServerInfo> {
  return requestJson<ServerInfo>("/info", "Failed to load daemon info");
}

export async function listAgents(): Promise<{ defaultAgent: string; agents: AgentInfo[] }> {
  const data = await requestJson<components["schemas"]["AgentListResponse"]>(
    "/agents",
    "Failed to load agents"
  );
  return {
    defaultAgent: data.default_agent,
    agents: data.agents ?? []
  };
}

export async function listWorkspaces(): Promise<Workspace[]> {
  const data = await requestJson<components["schemas"]["WorkspaceListResponse"]>(
    "/workspaces",
    "Failed to load workspaces"
  );
  return data.workspaces ?? [];
}

export async function registerWorkspace(rootPath: string, name?: string): Promise<Workspace> {
  return requestJson<Workspace>("/workspaces", "Failed to register workspace", {
    method: "POST",
    body: name ? { root_path: rootPath, name } : { root_path: rootPath }
  });
}

export async function deleteWorkspace(workspaceId: string): Promise<string> {
  const data = await requestJson<components["schemas"]["WorkspaceDeleteResponse"]>(
    `/workspaces/${encodeURIComponent(workspaceId)}`,
    "Failed to delete workspace",
    { method: "DELETE" }
  );
  return data.deleted;
}

export async function listWorkspaceFiles(
  workspaceId: string,
  opts: { path?: string; includeHidden?: boolean } = {}
): Promise<WorkspaceFiles> {
  const params = new URLSearchParams();
  if (opts.path) params.set("path", opts.path);
  if (opts.includeHidden) params.set("include_hidden", "true");
  const qs = params.toString();
  return requestJson<WorkspaceFiles>(
    `/workspaces/${encodeURIComponent(workspaceId)}/files${qs ? `?${qs}` : ""}`,
    "Failed to list workspace files"
  );
}

export async function readWorkspaceFile(
  workspaceId: string,
  path: string
): Promise<WorkspaceFileRead> {
  const params = new URLSearchParams({ path });
  return requestJson<WorkspaceFileRead>(
    `/workspaces/${encodeURIComponent(workspaceId)}/file?${params.toString()}`,
    "Failed to read file"
  );
}

export async function getGitStatus(workspaceId: string): Promise<GitStatus> {
  return requestJson<GitStatus>(
    `/workspaces/${encodeURIComponent(workspaceId)}/git/status`,
    "Failed to load git status"
  );
}

export async function getGitDiff(
  workspaceId: string,
  opts: { path?: string; staged?: boolean } = {}
): Promise<GitDiff> {
  const params = new URLSearchParams();
  if (opts.path) params.set("path", opts.path);
  if (opts.staged) params.set("staged", "true");
  const qs = params.toString();
  return requestJson<GitDiff>(
    `/workspaces/${encodeURIComponent(workspaceId)}/git/diff${qs ? `?${qs}` : ""}`,
    "Failed to load git diff"
  );
}

export async function listThreads(workspaceId: string): Promise<Thread[]> {
  const data = await requestJson<components["schemas"]["ThreadListResponse"]>(
    `/workspaces/${encodeURIComponent(workspaceId)}/threads`,
    "Failed to load threads"
  );
  return data.threads ?? [];
}

export async function createThread(
  workspaceId: string,
  opts: { title?: string; agentId?: string | null; model?: string | null } = {}
): Promise<Thread> {
  const body: Record<string, unknown> = {};
  if (opts.title) body.title = opts.title;
  if (opts.agentId) body.agent_id = opts.agentId;
  if (opts.model) body.model = opts.model;
  return requestJson<Thread>(
    `/workspaces/${encodeURIComponent(workspaceId)}/threads`,
    "Failed to create thread",
    { method: "POST", body }
  );
}

export async function getThread(threadId: string): Promise<Thread> {
  return requestJson<Thread>(
    `/threads/${encodeURIComponent(threadId)}`,
    "Failed to load thread"
  );
}

export async function updateThread(
  threadId: string,
  update: { title?: string; agent_id?: string | null; model?: string | null }
): Promise<Thread> {
  const payload: Record<string, string | null> = {};
  if (update.title !== undefined) payload.title = update.title;
  if (update.agent_id !== undefined) payload.agent_id = update.agent_id;
  if (update.model !== undefined) payload.model = update.model;
  return requestJson<Thread>(
    `/threads/${encodeURIComponent(threadId)}`,
    "Failed to update thread",
    { method: "PATCH", body: payload }
  );
}

export async function deleteThread(threadId: string): Promise<string> {
  const data = await requestJson<components["schemas"]["ThreadDeleteResponse"]>(
    `/threads/${encodeURIComponent(threadId)}`,
    "Failed to delete thread",
    { method: "DELETE" }
  );
  return data.deleted;
}

export async function clearThread(threadId: string): Promise<string> {
  const data = await requestJson<components["schemas"]["ThreadClearResponse"]>(
    `/threads/${encodeURIComponent(threadId)}/clear`,
    "Failed to clear thread",
    { method: "POST" }
  );
  return data.cleared;
}

export async function listThreadModels(
  threadId: string
): Promise<{ defaultModel: string; models: string[] }> {
  const data = await requestJson<components["schemas"]["ModelListResponse"]>(
    `/threads/${encodeURIComponent(threadId)}/models`,
    "Failed to load models"
  );
  return {
    defaultModel: data.default_model,
    models: data.models ?? []
  };
}

export async function listThreadItems(
  threadId: string,
  opts: { afterSeq?: number; limit?: number } = {}
): Promise<{ items: Item[]; hasMore: boolean }> {
  const params = new URLSearchParams();
  if (opts.afterSeq !== undefined) params.set("after_seq", String(opts.afterSeq));
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  const query = params.toString();
  const path = `/threads/${encodeURIComponent(threadId)}/items${query ? `?${query}` : ""}`;
  const data = await requestJson<components["schemas"]["ItemListResponse"]>(
    path,
    "Failed to load thread items"
  );
  return {
    items: data.items ?? [],
    hasMore: Boolean(data.has_more)
  };
}

export async function startRun(threadId: string, input: string): Promise<RunCreateResult> {
  return requestJson<RunCreateResult>(
    `/threads/${encodeURIComponent(threadId)}/runs`,
    "Failed to start run",
    { method: "POST", body: { input } }
  );
}

export async function cancelRun(runId: string): Promise<Run> {
  return requestJson<Run>(
    `/runs/${encodeURIComponent(runId)}/cancel`,
    "Failed to cancel run",
    { method: "POST" }
  );
}

export async function resolveApproval(
  runId: string,
  approvalId: string,
  approved: boolean,
  reason?: string
): Promise<ApprovalResolveResult> {
  return requestJson<ApprovalResolveResult>(
    `/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
    "Failed to resolve approval",
    {
      method: "POST",
      body: reason ? { approved, reason } : { approved }
    }
  );
}

export async function getPluginState(workspaceId: string, agentId: string): Promise<PluginState> {
  return requestJson<PluginState>(
    `/workspaces/${encodeURIComponent(workspaceId)}/plugins/${encodeURIComponent(agentId)}/state`,
    "Failed to load plugin state"
  );
}

// ---------------------------------------------------------------------------
// Auto-reconnecting SSE Event Bus
// ---------------------------------------------------------------------------

export type EventStreamOptions = {
  workspaceId?: string;
  threadId?: string;
  afterSeq?: number;
  signal: AbortSignal;
  onEvent: (event: LattisEvent) => void;
  onStatusChange?: (status: "connected" | "reconnecting" | "auth_required") => void;
};

export async function subscribeEvents({
  workspaceId,
  threadId,
  afterSeq,
  signal,
  onEvent,
  onStatusChange
}: EventStreamOptions): Promise<void> {
  let cursor = afterSeq;
  let backoffMs = 500;

  while (!signal.aborted) {
    try {
      const params = new URLSearchParams();
      if (workspaceId) params.set("workspace_id", workspaceId);
      if (threadId) params.set("thread_id", threadId);
      if (cursor !== undefined) params.set("after_seq", String(cursor));
      const query = params.toString();
      const headers = buildAuthHeaders({ Accept: "text/event-stream" });
      if (cursor !== undefined) {
        headers.set("Last-Event-ID", String(cursor));
      }

      const response = await fetch(buildUrl(`/events${query ? `?${query}` : ""}`), {
        method: "GET",
        headers,
        signal
      });

      if (response.status === 401) {
        onStatusChange?.("auth_required");
        return;
      }

      if (!response.ok || !response.body) {
        throw new Error(`SSE error: HTTP ${response.status}`);
      }

      backoffMs = 500;
      onStatusChange?.("connected");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      try {
        while (!signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          let boundary = buffer.indexOf("\n\n");
          while (boundary !== -1) {
            const frame = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);

            for (const line of frame.split(/\r?\n/)) {
              if (!line.startsWith("data:")) continue;
              const raw = line.slice(5).trimStart();
              if (!raw || raw === "[DONE]") continue;
              try {
                const parsed = JSON.parse(raw) as LattisEvent;
                if (typeof parsed.seq === "number" && parsed.seq > (cursor ?? 0)) {
                  cursor = parsed.seq;
                }
                onEvent(parsed);
              } catch {
                // ignore malformed frames
              }
            }
            boundary = buffer.indexOf("\n\n");
          }
        }
      } finally {
        reader.releaseLock();
      }
    } catch {
      if (signal.aborted) return;
    }

    if (signal.aborted) return;
    onStatusChange?.("reconnecting");
    await new Promise((resolve) => window.setTimeout(resolve, backoffMs));
    backoffMs = Math.min(backoffMs * 2, 5000);
  }
}

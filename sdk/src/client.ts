import type { components } from "./generated/openapi.js";
import type {
  AgentInfo,
  ApprovalResolveResult,
  EventConnectionStatus,
  GitDiff,
  GitStatus,
  Health,
  Item,
  LattisEvent,
  PluginState,
  Run,
  RunCreateResult,
  ServerInfo,
  Thread,
  Workspace,
  WorkspaceFileRead,
  WorkspaceFiles
} from "./types.js";

export class LattisApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(message: string, status: number, detail = "") {
    super(detail ? `${message}. ${detail}` : message);
    this.name = "LattisApiError";
    this.status = status;
    this.detail = detail;
  }
}

export class LattisAuthError extends LattisApiError {
  constructor(detail = "Invalid or missing authentication token.") {
    super("Authentication required", 401, detail);
    this.name = "LattisAuthError";
  }
}

export type TokenProvider = string | null | (() => string | null | undefined);

export type LattisClientOptions = {
  baseUrl?: string;
  token?: TokenProvider;
  fetch?: typeof globalThis.fetch;
};

export type EventSubscriptionOptions = {
  workspaceId?: string;
  threadId?: string;
  afterSeq?: number;
  signal: AbortSignal;
  onEvent: (event: LattisEvent) => void;
  onStatusChange?: (status: EventConnectionStatus) => void;
};

type RequestJsonOptions = Omit<RequestInit, "body"> & { body?: unknown };

export class LattisClient {
  readonly baseUrl: string;
  private tokenProvider: TokenProvider;
  private readonly fetchImpl: typeof globalThis.fetch;

  constructor(options: LattisClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? "http://127.0.0.1:7700").replace(/\/+$/, "");
    this.tokenProvider = options.token ?? null;
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  setToken(token: TokenProvider): void {
    this.tokenProvider = token;
  }

  private resolveToken(): string | null {
    const raw =
      typeof this.tokenProvider === "function" ? this.tokenProvider() : this.tokenProvider;
    return raw && raw.trim() ? raw.trim() : null;
  }

  private buildUrl(path: string): string {
    return new URL(path, `${this.baseUrl}/`).toString();
  }

  private buildHeaders(extra?: HeadersInit): Headers {
    const headers = new Headers(extra);
    const token = this.resolveToken();
    if (token && !headers.has("Authorization")) {
      headers.set("Authorization", `Bearer ${token}`);
    }
    return headers;
  }

  private async extractDetail(response: Response): Promise<string> {
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string" && data.detail) {
        return data.detail;
      }
    } catch {
      // ignore non-JSON error responses
    }
    return "";
  }

  private async request(
    path: string,
    fallbackMessage: string,
    init: RequestInit = {}
  ): Promise<Response> {
    const response = await this.fetchImpl(this.buildUrl(path), {
      ...init,
      headers: this.buildHeaders(init.headers)
    });
    if (response.ok) return response;
    const detail = await this.extractDetail(response);
    if (response.status === 401) {
      throw new LattisAuthError(detail || undefined);
    }
    throw new LattisApiError(fallbackMessage, response.status, detail);
  }

  private async requestJson<T>(
    path: string,
    fallbackMessage: string,
    options: RequestJsonOptions = {}
  ): Promise<T> {
    const { body, headers, ...rest } = options;
    const finalHeaders = this.buildHeaders(headers);
    if (body !== undefined && !finalHeaders.has("Content-Type")) {
      finalHeaders.set("Content-Type", "application/json");
    }
    const response = await this.request(path, fallbackMessage, {
      ...rest,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    return (await response.json()) as T;
  }

  // -------------------------------------------------------------------------
  // System & Agents
  // -------------------------------------------------------------------------

  async health(): Promise<Health> {
    return this.requestJson<Health>("/health", "Health check failed");
  }

  async info(): Promise<ServerInfo> {
    return this.requestJson<ServerInfo>("/info", "Failed to load daemon info");
  }

  async listAgents(): Promise<{ defaultAgent: string; agents: AgentInfo[] }> {
    const data = await this.requestJson<components["schemas"]["AgentListResponse"]>(
      "/agents",
      "Failed to load agents"
    );
    return { defaultAgent: data.default_agent, agents: data.agents ?? [] };
  }

  // -------------------------------------------------------------------------
  // Workspaces & Workspace Inspection
  // -------------------------------------------------------------------------

  async listWorkspaces(): Promise<Workspace[]> {
    const data = await this.requestJson<components["schemas"]["WorkspaceListResponse"]>(
      "/workspaces",
      "Failed to load workspaces"
    );
    return data.workspaces ?? [];
  }

  async registerWorkspace(rootPath: string, name?: string): Promise<Workspace> {
    return this.requestJson<Workspace>("/workspaces", "Failed to register workspace", {
      method: "POST",
      body: name ? { root_path: rootPath, name } : { root_path: rootPath }
    });
  }

  async getWorkspace(workspaceId: string): Promise<Workspace> {
    return this.requestJson<Workspace>(
      `/workspaces/${encodeURIComponent(workspaceId)}`,
      "Failed to load workspace"
    );
  }

  async updateWorkspace(
    workspaceId: string,
    update: { name?: string; settings?: Record<string, unknown> }
  ): Promise<Workspace> {
    return this.requestJson<Workspace>(
      `/workspaces/${encodeURIComponent(workspaceId)}`,
      "Failed to update workspace",
      { method: "PATCH", body: update }
    );
  }

  async deleteWorkspace(workspaceId: string): Promise<string> {
    const data = await this.requestJson<components["schemas"]["WorkspaceDeleteResponse"]>(
      `/workspaces/${encodeURIComponent(workspaceId)}`,
      "Failed to delete workspace",
      { method: "DELETE" }
    );
    return data.deleted;
  }

  async listFiles(
    workspaceId: string,
    opts: { path?: string; includeHidden?: boolean; limit?: number } = {}
  ): Promise<WorkspaceFiles> {
    const params = new URLSearchParams();
    if (opts.path) params.set("path", opts.path);
    if (opts.includeHidden) params.set("include_hidden", "true");
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return this.requestJson<WorkspaceFiles>(
      `/workspaces/${encodeURIComponent(workspaceId)}/files${qs ? `?${qs}` : ""}`,
      "Failed to list workspace files"
    );
  }

  async readFile(
    workspaceId: string,
    path: string,
    opts: { maxBytes?: number } = {}
  ): Promise<WorkspaceFileRead> {
    const params = new URLSearchParams({ path });
    if (opts.maxBytes !== undefined) params.set("max_bytes", String(opts.maxBytes));
    return this.requestJson<WorkspaceFileRead>(
      `/workspaces/${encodeURIComponent(workspaceId)}/file?${params.toString()}`,
      "Failed to read file"
    );
  }

  async gitStatus(workspaceId: string): Promise<GitStatus> {
    return this.requestJson<GitStatus>(
      `/workspaces/${encodeURIComponent(workspaceId)}/git/status`,
      "Failed to load git status"
    );
  }

  async gitDiff(
    workspaceId: string,
    opts: { path?: string; staged?: boolean } = {}
  ): Promise<GitDiff> {
    const params = new URLSearchParams();
    if (opts.path) params.set("path", opts.path);
    if (opts.staged) params.set("staged", "true");
    const qs = params.toString();
    return this.requestJson<GitDiff>(
      `/workspaces/${encodeURIComponent(workspaceId)}/git/diff${qs ? `?${qs}` : ""}`,
      "Failed to load git diff"
    );
  }

  // -------------------------------------------------------------------------
  // Threads & Items
  // -------------------------------------------------------------------------

  async listThreads(workspaceId: string): Promise<Thread[]> {
    const data = await this.requestJson<components["schemas"]["ThreadListResponse"]>(
      `/workspaces/${encodeURIComponent(workspaceId)}/threads`,
      "Failed to load threads"
    );
    return data.threads ?? [];
  }

  async createThread(
    workspaceId: string,
    opts: { threadId?: string; title?: string; agentId?: string | null; model?: string | null } = {}
  ): Promise<Thread> {
    const body: Record<string, unknown> = {};
    if (opts.threadId) body.thread_id = opts.threadId;
    if (opts.title) body.title = opts.title;
    if (opts.agentId) body.agent_id = opts.agentId;
    if (opts.model) body.model = opts.model;
    return this.requestJson<Thread>(
      `/workspaces/${encodeURIComponent(workspaceId)}/threads`,
      "Failed to create thread",
      { method: "POST", body }
    );
  }

  async getThread(threadId: string): Promise<Thread> {
    return this.requestJson<Thread>(
      `/threads/${encodeURIComponent(threadId)}`,
      "Failed to load thread"
    );
  }

  async updateThread(
    threadId: string,
    update: { title?: string; agent_id?: string | null; model?: string | null }
  ): Promise<Thread> {
    return this.requestJson<Thread>(
      `/threads/${encodeURIComponent(threadId)}`,
      "Failed to update thread",
      { method: "PATCH", body: update }
    );
  }

  async deleteThread(threadId: string): Promise<string> {
    const data = await this.requestJson<components["schemas"]["ThreadDeleteResponse"]>(
      `/threads/${encodeURIComponent(threadId)}`,
      "Failed to delete thread",
      { method: "DELETE" }
    );
    return data.deleted;
  }

  async clearThread(threadId: string): Promise<string> {
    const data = await this.requestJson<components["schemas"]["ThreadClearResponse"]>(
      `/threads/${encodeURIComponent(threadId)}/clear`,
      "Failed to clear thread",
      { method: "POST" }
    );
    return data.cleared;
  }

  async listThreadModels(
    threadId: string
  ): Promise<{ defaultModel: string; models: string[] }> {
    const data = await this.requestJson<components["schemas"]["ModelListResponse"]>(
      `/threads/${encodeURIComponent(threadId)}/models`,
      "Failed to load models"
    );
    return { defaultModel: data.default_model, models: data.models ?? [] };
  }

  async listThreadItems(
    threadId: string,
    opts: { afterSeq?: number; limit?: number } = {}
  ): Promise<{ items: Item[]; hasMore: boolean }> {
    const params = new URLSearchParams();
    if (opts.afterSeq !== undefined) params.set("after_seq", String(opts.afterSeq));
    if (opts.limit !== undefined) params.set("limit", String(opts.limit));
    const qs = params.toString();
    const data = await this.requestJson<components["schemas"]["ItemListResponse"]>(
      `/threads/${encodeURIComponent(threadId)}/items${qs ? `?${qs}` : ""}`,
      "Failed to load thread items"
    );
    return { items: data.items ?? [], hasMore: Boolean(data.has_more) };
  }

  // -------------------------------------------------------------------------
  // Runs, Approvals & Plugins
  // -------------------------------------------------------------------------

  async startRun(threadId: string, input: string): Promise<RunCreateResult> {
    return this.requestJson<RunCreateResult>(
      `/threads/${encodeURIComponent(threadId)}/runs`,
      "Failed to start run",
      { method: "POST", body: { input } }
    );
  }

  async listRuns(threadId: string, limit = 50): Promise<Run[]> {
    const data = await this.requestJson<components["schemas"]["RunListResponse"]>(
      `/threads/${encodeURIComponent(threadId)}/runs?limit=${limit}`,
      "Failed to load runs"
    );
    return data.runs ?? [];
  }

  async getRun(runId: string): Promise<Run> {
    return this.requestJson<Run>(
      `/runs/${encodeURIComponent(runId)}`,
      "Failed to load run"
    );
  }

  async cancelRun(runId: string): Promise<Run> {
    return this.requestJson<Run>(
      `/runs/${encodeURIComponent(runId)}/cancel`,
      "Failed to cancel run",
      { method: "POST" }
    );
  }

  async resolveApproval(
    runId: string,
    approvalId: string,
    approved: boolean,
    reason?: string
  ): Promise<ApprovalResolveResult> {
    return this.requestJson<ApprovalResolveResult>(
      `/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}`,
      "Failed to resolve approval",
      { method: "POST", body: reason ? { approved, reason } : { approved } }
    );
  }

  async getPluginState(workspaceId: string, agentId: string): Promise<PluginState> {
    return this.requestJson<PluginState>(
      `/workspaces/${encodeURIComponent(workspaceId)}/plugins/${encodeURIComponent(agentId)}/state`,
      "Failed to load plugin state"
    );
  }

  // -------------------------------------------------------------------------
  // Auto-reconnecting SSE Event Bus
  // -------------------------------------------------------------------------

  async subscribeEvents({
    workspaceId,
    threadId,
    afterSeq,
    signal,
    onEvent,
    onStatusChange
  }: EventSubscriptionOptions): Promise<void> {
    let cursor = afterSeq;
    let backoffMs = 500;

    while (!signal.aborted) {
      try {
        const params = new URLSearchParams();
        if (workspaceId) params.set("workspace_id", workspaceId);
        if (threadId) params.set("thread_id", threadId);
        if (cursor !== undefined) params.set("after_seq", String(cursor));
        const qs = params.toString();
        const headers = this.buildHeaders({ Accept: "text/event-stream" });
        if (cursor !== undefined) {
          headers.set("Last-Event-ID", String(cursor));
        }

        const response = await this.fetchImpl(this.buildUrl(`/events${qs ? `?${qs}` : ""}`), {
          method: "GET",
          headers,
          signal
        });

        if (response.status === 401) {
          onStatusChange?.("auth_required");
          return;
        }
        if (!response.ok || !response.body) {
          throw new Error(`SSE HTTP ${response.status}`);
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
      await new Promise((resolve) => setTimeout(resolve, backoffMs));
      backoffMs = Math.min(backoffMs * 2, 5000);
    }
  }
}

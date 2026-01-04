import { streamUiEvents, type UiMessage, type UiStreamEvent } from "@/services/vercel";
import type { components } from "@/generated/openapi";

const FALLBACK_HOST =
  typeof window !== "undefined" ? window.location.hostname : "localhost";
const DEFAULT_SERVER_URL = `http://${FALLBACK_HOST}:8000`;

export const SERVER_URL =
  (import.meta.env.VITE_LATTICE_SERVER_URL as string | undefined) ||
  DEFAULT_SERVER_URL;

type RequestJsonOptions = Omit<RequestInit, "body"> & { body?: unknown };

function toNullable(value?: string | null) {
  return value && value.trim() ? value : null;
}

function buildUrl(path: string) {
  return new URL(path, SERVER_URL).toString();
}

async function getErrorDetail(response: Response) {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data.detail === "string" && data.detail) {
      return ` ${data.detail}`;
    }
  } catch {
    // ignore JSON errors
  }
  return "";
}

async function request(
  path: string,
  fallbackMessage: string,
  options: RequestInit
) {
  const response = await fetch(buildUrl(path), options);
  if (response.ok) {
    return response;
  }
  const detail = await getErrorDetail(response);
  throw new Error(`${fallbackMessage}.${detail}`);
}

async function requestJson<T>(
  path: string,
  fallbackMessage: string,
  options: RequestJsonOptions = {}
): Promise<T> {
  const { body, headers, ...rest } = options;
  const init: RequestInit = {
    ...rest,
    headers:
      body === undefined
        ? headers
        : {
            "Content-Type": "application/json",
            ...headers
          },
    body: body === undefined ? undefined : JSON.stringify(body)
  };
  const response = await request(path, fallbackMessage, init);
  return (await response.json()) as T;
}

export type AgentSelection = {
  agent: string | null;
  defaultAgent: string | null;
  isDefault: boolean;
  agentName: string | null;
};

export type ModelSelection = {
  model: string | null;
  defaultModel: string | null;
  isDefault: boolean;
};

export type ThreadState = {
  threadId: string;
  agent: AgentSelection;
  model: ModelSelection;
  messages: UiMessage[];
};

export type SessionBootstrap = {
  sessionId: string;
  threadId: string;
  threads: string[];
  agent: AgentSelection;
  model: ModelSelection;
  messages: UiMessage[];
};

export type ThreadStateUpdate = {
  agent?: string | null;
  model?: string | null;
};

function mapAgentSelection(
  data: components["schemas"]["ThreadAgentResponse"]
): AgentSelection {
  return {
    agent: toNullable(data.agent),
    defaultAgent: toNullable(data.default_agent),
    isDefault: Boolean(data.is_default),
    agentName: toNullable(data.agent_name)
  };
}

function mapModelSelection(
  data: components["schemas"]["SessionModelResponse"]
): ModelSelection {
  return {
    model: toNullable(data.model),
    defaultModel: toNullable(data.default_model),
    isDefault: Boolean(data.is_default)
  };
}

function mapThreadState(
  data: components["schemas"]["ThreadStateResponse"],
  fallbackThreadId: string
): ThreadState {
  const messages = (data.messages ?? []) as UiMessage[];
  return {
    threadId: data.thread_id ?? fallbackThreadId,
    agent: mapAgentSelection(data.agent),
    model: mapModelSelection(data.model),
    messages
  };
}

export async function listThreadModels(
  sessionId: string,
  threadId: string
): Promise<{ defaultModel: string | null; models: string[] }> {
  const data = await requestJson<components["schemas"]["ModelListResponse"]>(
    `/sessions/${sessionId}/threads/${threadId}/models`,
    "Failed to load models"
  );
  return {
    defaultModel: toNullable(data.default_model),
    models: data.models ?? []
  };
}

export type AgentInfo = components["schemas"]["AgentInfo"];

export async function listAgents(): Promise<{
  defaultAgent: string | null;
  agents: AgentInfo[];
}> {
  const data = await requestJson<components["schemas"]["AgentListResponse"]>(
    "/agents",
    "Failed to load agents"
  );
  const agents = data.agents ?? [];
  return {
    defaultAgent: toNullable(data.default_agent),
    agents: agents.filter((item) => Boolean(item.id))
  };
}

export async function listThreads(sessionId: string): Promise<string[]> {
  const data = await requestJson<components["schemas"]["ThreadListResponse"]>(
    `/sessions/${sessionId}/threads`,
    "Failed to load threads"
  );
  return data.threads ?? [];
}

export async function createThread(
  sessionId: string,
  threadId?: string
): Promise<string> {
  const data = await requestJson<components["schemas"]["ThreadCreateResponse"]>(
    `/sessions/${sessionId}/threads`,
    "Failed to create thread",
    {
      method: "POST",
      body: threadId ? { thread_id: threadId } : {}
    }
  );
  if (!data.thread_id) {
    throw new Error("Server did not return a thread id.");
  }
  return data.thread_id;
}

export async function deleteThread(
  sessionId: string,
  threadId: string
): Promise<string> {
  const data = await requestJson<components["schemas"]["ThreadDeleteResponse"]>(
    `/sessions/${sessionId}/threads/${threadId}`,
    "Failed to delete thread",
    { method: "DELETE" }
  );
  return data.deleted ?? threadId;
}

export async function clearThread(
  sessionId: string,
  threadId: string
): Promise<string> {
  const data = await requestJson<components["schemas"]["ThreadClearResponse"]>(
    `/sessions/${sessionId}/threads/${threadId}/clear`,
    "Failed to clear thread",
    { method: "POST" }
  );
  return data.cleared ?? threadId;
}

export async function getThreadState(
  sessionId: string,
  threadId: string
): Promise<ThreadState> {
  const data = await requestJson<components["schemas"]["ThreadStateResponse"]>(
    `/sessions/${sessionId}/threads/${threadId}/state`,
    "Failed to load thread state"
  );
  return mapThreadState(data, threadId);
}

export async function updateThreadState(
  sessionId: string,
  threadId: string,
  update: ThreadStateUpdate
): Promise<ThreadState> {
  const payload: Record<string, string | null> = {};
  if (update.agent !== undefined) {
    payload.agent = update.agent;
  }
  if (update.model !== undefined) {
    payload.model = update.model;
  }
  const data = await requestJson<components["schemas"]["ThreadStateResponse"]>(
    `/sessions/${sessionId}/threads/${threadId}/state`,
    "Failed to update thread state",
    {
      method: "PATCH",
      body: payload
    }
  );
  return mapThreadState(data, threadId);
}

export async function bootstrapSession(
  threadId?: string
): Promise<SessionBootstrap> {
  const path = threadId
    ? `/session/bootstrap?thread_id=${encodeURIComponent(threadId)}`
    : "/session/bootstrap";
  const data = await requestJson<components["schemas"]["SessionBootstrapResponse"]>(
    path,
    "Failed to bootstrap session"
  );
  const mapped = mapThreadState(
    data as components["schemas"]["ThreadStateResponse"],
    data.thread_id ?? ""
  );
  return {
    sessionId: data.session_id ?? "",
    threadId: mapped.threadId,
    threads: data.threads ?? [],
    agent: mapped.agent,
    model: mapped.model,
    messages: mapped.messages
  };
}

export async function runChatStream(
  payload: Record<string, unknown>,
  signal?: AbortSignal
): Promise<AsyncGenerator<UiStreamEvent>> {
  const response = await request(
    "/ui/chat",
    "Failed to run agent",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        accept: "text/event-stream"
      },
      body: JSON.stringify(payload),
      signal
    }
  );
  return streamUiEvents(response, signal);
}

import { UiMessage, UiStreamEvent, streamUiEvents } from "@/lib/vercel";
import type { components } from "@/lib/openapi";

const FALLBACK_HOST =
  typeof window !== "undefined" ? window.location.hostname : "localhost";
const DEFAULT_SERVER_URL = `http://${FALLBACK_HOST}:8000`;

export const SERVER_URL =
  (import.meta.env.VITE_LATTICE_SERVER_URL as string | undefined) ||
  DEFAULT_SERVER_URL;

async function ensureOk(response: Response, fallbackMessage: string) {
  if (response.ok) {
    return;
  }
  let detail = "";
  try {
    const data = await response.json();
    detail = data?.detail ? ` ${data.detail}` : "";
  } catch {
    // ignore JSON errors
  }
  throw new Error(`${fallbackMessage}.${detail}`);
}

export type AgentSelection = {
  agent: string;
  defaultAgent: string;
  isDefault: boolean;
  agentName: string;
};

export type ModelSelection = {
  model: string;
  defaultModel: string;
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
    agent: data.agent ?? "",
    defaultAgent: data.default_agent ?? "",
    isDefault: Boolean(data.is_default),
    agentName: data.agent_name ?? ""
  };
}

function mapModelSelection(
  data: components["schemas"]["SessionModelResponse"]
): ModelSelection {
  return {
    model: data.model ?? "",
    defaultModel: data.default_model ?? "",
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
): Promise<{ defaultModel: string; models: string[] }> {
  const response = await fetch(
    `${SERVER_URL}/sessions/${sessionId}/threads/${threadId}/models`
  );
  await ensureOk(response, "Failed to load models");
  const data = (await response.json()) as components["schemas"]["ModelListResponse"];
  return {
    defaultModel: data.default_model ?? "",
    models: data.models ?? []
  };
}

export type AgentInfo = components["schemas"]["AgentInfo"];

export async function listAgents(): Promise<{ defaultAgent: string; agents: AgentInfo[] }> {
  const response = await fetch(`${SERVER_URL}/agents`);
  await ensureOk(response, "Failed to load agents");
  const data = (await response.json()) as components["schemas"]["AgentListResponse"];
  const agents = data.agents ?? [];
  return {
    defaultAgent: data.default_agent ?? "",
    agents: agents.filter((item) => Boolean(item.id))
  };
}

export async function listThreads(sessionId: string): Promise<string[]> {
  const response = await fetch(`${SERVER_URL}/sessions/${sessionId}/threads`);
  await ensureOk(response, "Failed to load threads");
  const data = (await response.json()) as components["schemas"]["ThreadListResponse"];
  return data.threads ?? [];
}

export async function createThread(sessionId: string, threadId?: string): Promise<string> {
  const response = await fetch(`${SERVER_URL}/sessions/${sessionId}/threads`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(threadId ? { thread_id: threadId } : {})
  });
  await ensureOk(response, "Failed to create thread");
  const data = (await response.json()) as components["schemas"]["ThreadCreateResponse"];
  if (!data.thread_id) {
    throw new Error("Server did not return a thread id.");
  }
  return data.thread_id;
}

export async function deleteThread(sessionId: string, threadId: string): Promise<string> {
  const response = await fetch(
    `${SERVER_URL}/sessions/${sessionId}/threads/${threadId}`,
    { method: "DELETE" }
  );
  await ensureOk(response, "Failed to delete thread");
  const data = (await response.json()) as components["schemas"]["ThreadDeleteResponse"];
  return data.deleted ?? threadId;
}

export async function clearThread(sessionId: string, threadId: string): Promise<string> {
  const response = await fetch(
    `${SERVER_URL}/sessions/${sessionId}/threads/${threadId}/clear`,
    { method: "POST" }
  );
  await ensureOk(response, "Failed to clear thread");
  const data = (await response.json()) as components["schemas"]["ThreadClearResponse"];
  return data.cleared ?? threadId;
}

export async function getThreadState(
  sessionId: string,
  threadId: string
): Promise<ThreadState> {
  const response = await fetch(
    `${SERVER_URL}/sessions/${sessionId}/threads/${threadId}/state`
  );
  await ensureOk(response, "Failed to load thread state");
  const data = (await response.json()) as components["schemas"]["ThreadStateResponse"];
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
  const response = await fetch(
    `${SERVER_URL}/sessions/${sessionId}/threads/${threadId}/state`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    }
  );
  await ensureOk(response, "Failed to update thread state");
  const data = (await response.json()) as components["schemas"]["ThreadStateResponse"];
  return mapThreadState(data, threadId);
}

export async function bootstrapSession(threadId?: string): Promise<SessionBootstrap> {
  const url = threadId
    ? `${SERVER_URL}/session/bootstrap?thread_id=${encodeURIComponent(threadId)}`
    : `${SERVER_URL}/session/bootstrap`;
  const response = await fetch(url);
  await ensureOk(response, "Failed to bootstrap session");
  const data = (await response.json()) as components["schemas"]["SessionBootstrapResponse"];
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
  const response = await fetch(`${SERVER_URL}/ui/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      accept: "text/event-stream"
    },
    body: JSON.stringify(payload),
    signal
  });
  await ensureOk(response, "Failed to run agent");
  return streamUiEvents(response, signal);
}

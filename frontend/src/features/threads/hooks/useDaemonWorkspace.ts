import React from "react";

import {
  cancelRun,
  clearThread as clearThreadRequest,
  createThread as createThreadRequest,
  deleteThread as deleteThreadRequest,
  getAuthToken,
  getGitStatus,
  getPluginState,
  listAgents,
  listThreadItems,
  listThreadModels,
  listThreads,
  listWorkspaces,
  registerWorkspace as registerWorkspaceRequest,
  resolveApproval as resolveApprovalRequest,
  setAuthToken,
  startRun,
  subscribeEvents,
  UnauthorizedError,
  updateThread,
  type AgentInfo,
  type GitStatus,
  type Item,
  type LattisEvent,
  type Thread,
  type Workspace
} from "@/services/lattisClient";

const STATUS_TIMEOUT_MS = 2500;

type UseDaemonWorkspaceParams = {
  hydrateItems: (items: Item[]) => void;
  upsertItem: (item: Item) => void;
  clearItems: () => void;
  onThreadEvent: (event: LattisEvent) => void;
  addSystemMessage: (content: string) => void;
};

export function useDaemonWorkspace({
  hydrateItems,
  upsertItem,
  clearItems,
  onThreadEvent,
  addSystemMessage
}: UseDaemonWorkspaceParams) {
  const [workspaces, setWorkspaces] = React.useState<Workspace[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = React.useState<string | null>(null);
  const [threads, setThreads] = React.useState<Thread[]>([]);
  const [currentThreadId, setCurrentThreadId] = React.useState<string | null>(null);

  const [agents, setAgents] = React.useState<AgentInfo[] | null>(null);
  const [defaultAgentId, setDefaultAgentId] = React.useState<string | null>(null);
  const [models, setModels] = React.useState<string[] | null>(null);

  const [pluginState, setPluginState] = React.useState<Record<string, unknown> | null>(null);
  const [isLoadingPluginState, setIsLoadingPluginState] = React.useState(false);
  const [gitStatus, setGitStatus] = React.useState<GitStatus | null>(null);
  const [isLoadingGitStatus, setIsLoadingGitStatus] = React.useState(false);

  const [isLoadingThreads, setIsLoadingThreads] = React.useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = React.useState(false);
  const [isLoadingAgents, setIsLoadingAgents] = React.useState(false);
  const [isLoadingModels, setIsLoadingModels] = React.useState(false);
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const [connectionState, setConnectionState] = React.useState<
    "connected" | "reconnecting" | "auth_required" | "error"
  >("reconnecting");
  const [authError, setAuthError] = React.useState<string | null>(null);
  const [authRevision, setAuthRevision] = React.useState(0);

  const statusTimeout = React.useRef<number | null>(null);
  const activeWorkspaceRef = React.useRef<string | null>(null);
  const currentThreadRef = React.useRef<string | null>(null);
  const currentAgentRef = React.useRef<string | null>(null);

  const currentThread = React.useMemo(
    () => threads.find((t) => t.id === currentThreadId) ?? null,
    [threads, currentThreadId]
  );

  const activeWorkspace = React.useMemo(
    () => workspaces.find((w) => w.id === activeWorkspaceId) ?? null,
    [workspaces, activeWorkspaceId]
  );

  React.useEffect(() => {
    activeWorkspaceRef.current = activeWorkspaceId;
  }, [activeWorkspaceId]);

  React.useEffect(() => {
    currentThreadRef.current = currentThreadId;
  }, [currentThreadId]);

  React.useEffect(() => {
    currentAgentRef.current = currentThread?.resolved_agent.agent ?? null;
  }, [currentThread]);

  const setStatus = React.useCallback((message: string | null, timeout = STATUS_TIMEOUT_MS) => {
    if (statusTimeout.current) {
      window.clearTimeout(statusTimeout.current);
      statusTimeout.current = null;
    }
    setStatusMessage(message);
    if (message && timeout > 0) {
      statusTimeout.current = window.setTimeout(() => {
        setStatusMessage(null);
      }, timeout);
    }
  }, []);

  React.useEffect(() => {
    return () => {
      if (statusTimeout.current) {
        window.clearTimeout(statusTimeout.current);
      }
    };
  }, []);

  const handleError = React.useCallback(
    (error: unknown, fallback: string) => {
      if (error instanceof UnauthorizedError) {
        setConnectionState("auth_required");
        setAuthError(getAuthToken() ? error.message : null);
        return;
      }
      setStatus(error instanceof Error ? error.message : fallback, 0);
    },
    [setStatus]
  );

  const loadThreadHistory = React.useCallback(
    async (threadId: string) => {
      setIsLoadingHistory(true);
      try {
        const result = await listThreadItems(threadId);
        if (currentThreadRef.current === threadId) {
          hydrateItems(result.items);
        }
      } catch (error) {
        if (error instanceof UnauthorizedError) {
          setConnectionState("auth_required");
          setAuthError(error.message);
          return;
        }
        addSystemMessage(
          `Failed to load history: ${error instanceof Error ? error.message : String(error)}`
        );
      } finally {
        setIsLoadingHistory(false);
      }
    },
    [addSystemMessage, hydrateItems]
  );

  const loadWorkspaceThreads = React.useCallback(
    async (workspaceId: string, preferredThreadId?: string | null) => {
      setIsLoadingThreads(true);
      try {
        let list = await listThreads(workspaceId);
        if (list.length === 0) {
          const created = await createThreadRequest(workspaceId);
          list = [created];
        }
        setThreads(list);
        const target =
          (preferredThreadId && list.find((t) => t.id === preferredThreadId)?.id) ||
          list[0].id;
        setCurrentThreadId(target);
        currentThreadRef.current = target;
        setModels(null);
        await loadThreadHistory(target);
      } catch (error) {
        handleError(error, "Failed to load threads");
      } finally {
        setIsLoadingThreads(false);
      }
    },
    [handleError, loadThreadHistory]
  );

  const refreshAll = React.useCallback(async () => {
    try {
      const [wsList, agentPayload] = await Promise.all([listWorkspaces(), listAgents()]);
      setWorkspaces(wsList);
      setAgents(agentPayload.agents);
      setDefaultAgentId(agentPayload.defaultAgent);
      setAuthError(null);

      const preferredWs =
        (activeWorkspaceRef.current &&
          wsList.find((w) => w.id === activeWorkspaceRef.current)?.id) ||
        wsList[0]?.id ||
        null;

      setActiveWorkspaceId(preferredWs);
      activeWorkspaceRef.current = preferredWs;
      if (preferredWs) {
        await loadWorkspaceThreads(preferredWs, currentThreadRef.current);
      }
    } catch (error) {
      handleError(error, "Failed to connect to Lattis daemon");
    }
  }, [handleError, loadWorkspaceThreads]);

  // Initial load + reload on auth token change
  React.useEffect(() => {
    void refreshAll();
  }, [authRevision, refreshAll]);

  // Load plugin state whenever active workspace or thread agent changes
  const activeAgentInfo = React.useMemo(() => {
    const aid = currentThread?.resolved_agent.agent;
    if (!aid || !agents) return null;
    return agents.find((a) => a.id === aid) ?? null;
  }, [agents, currentThread]);

  const refreshPluginState = React.useCallback(async () => {
    const wsId = activeWorkspaceId;
    const aid = currentThread?.resolved_agent.agent;
    if (!wsId || !aid || !activeAgentInfo?.has_state) {
      setPluginState(null);
      return;
    }
    setIsLoadingPluginState(true);
    try {
      const res = await getPluginState(wsId, aid);
      setPluginState((res.state as Record<string, unknown> | null) ?? null);
    } catch {
      // ignore transient errors
    } finally {
      setIsLoadingPluginState(false);
    }
  }, [activeAgentInfo?.has_state, activeWorkspaceId, currentThread?.resolved_agent.agent]);

  React.useEffect(() => {
    void refreshPluginState();
  }, [refreshPluginState]);

  const refreshGitStatus = React.useCallback(async () => {
    const wsId = activeWorkspaceRef.current;
    if (!wsId) {
      setGitStatus(null);
      return;
    }
    setIsLoadingGitStatus(true);
    try {
      const res = await getGitStatus(wsId);
      if (activeWorkspaceRef.current === wsId) {
        setGitStatus(res);
      }
    } catch {
      // ignore transient errors
    } finally {
      setIsLoadingGitStatus(false);
    }
  }, []);

  React.useEffect(() => {
    void refreshGitStatus();
  }, [activeWorkspaceId, refreshGitStatus]);

  // Global SSE Event Bus subscription (live multi-client sync)
  React.useEffect(() => {
    const controller = new AbortController();

    void subscribeEvents({
      signal: controller.signal,
      onStatusChange: (status) => {
        setConnectionState(status);
      },
      onEvent: (event) => {
        if (event.type === "bus.resync_required") {
          void refreshAll();
          return;
        }

        if (event.type === "workspace.created") {
          setWorkspaces((prev) =>
            prev.some((w) => w.id === event.data.id) ? prev : [...prev, event.data]
          );
          return;
        }
        if (event.type === "workspace.updated") {
          setWorkspaces((prev) =>
            prev.map((w) => (w.id === event.data.id ? event.data : w))
          );
          return;
        }
        if (event.type === "workspace.deleted") {
          setWorkspaces((prev) => prev.filter((w) => w.id !== event.data.workspace_id));
          return;
        }

        if (event.type === "thread.created") {
          if (event.workspace_id === activeWorkspaceRef.current) {
            setThreads((prev) =>
              prev.some((t) => t.id === event.data.id) ? prev : [event.data, ...prev]
            );
          }
          setWorkspaces((prev) =>
            prev.map((w) =>
              w.id === event.workspace_id
                ? { ...w, thread_count: (w.thread_count ?? 0) + 1 }
                : w
            )
          );
          return;
        }
        if (event.type === "thread.updated") {
          if (event.workspace_id === activeWorkspaceRef.current) {
            setThreads((prev) =>
              prev.map((t) => (t.id === event.data.id ? event.data : t))
            );
          }
          return;
        }
        if (event.type === "thread.deleted") {
          setThreads((prev) => prev.filter((t) => t.id !== event.data.thread_id));
          setWorkspaces((prev) =>
            prev.map((w) =>
              w.id === event.workspace_id
                ? { ...w, thread_count: Math.max(0, (w.thread_count ?? 0) - 1) }
                : w
            )
          );
          return;
        }

        if (event.type === "plugin.state_updated") {
          if (
            event.data.workspace_id === activeWorkspaceRef.current &&
            event.data.agent_id === currentAgentRef.current
          ) {
            setPluginState((event.data.state as Record<string, unknown> | null) ?? null);
          }
          return;
        }

        // Forward active-thread item & run events to the chat timeline
        if (event.thread_id && event.thread_id === currentThreadRef.current) {
          onThreadEvent(event);
        }

        // Refresh git status when a run completes or a tool call finishes in the active workspace
        if (
          event.workspace_id === activeWorkspaceRef.current &&
          (event.type === "run.completed" ||
            (event.type === "item.completed" && event.data.kind === "tool_call"))
        ) {
          void refreshGitStatus();
        }
      }
    });

    return () => controller.abort();
  }, [authRevision, onThreadEvent, refreshAll, refreshGitStatus]);

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  const selectWorkspace = React.useCallback(
    async (workspaceId: string) => {
      if (workspaceId === activeWorkspaceId) return;
      setActiveWorkspaceId(workspaceId);
      activeWorkspaceRef.current = workspaceId;
      clearItems();
      await loadWorkspaceThreads(workspaceId, null);
    },
    [activeWorkspaceId, clearItems, loadWorkspaceThreads]
  );

  const registerWorkspace = React.useCallback(
    async (rootPath: string) => {
      try {
        const ws = await registerWorkspaceRequest(rootPath);
        setWorkspaces((prev) => (prev.some((w) => w.id === ws.id) ? prev : [...prev, ws]));
        setActiveWorkspaceId(ws.id);
        activeWorkspaceRef.current = ws.id;
        clearItems();
        await loadWorkspaceThreads(ws.id, null);
        setStatus(`Opened ${ws.name}`);
      } catch (error) {
        handleError(error, "Failed to register workspace");
      }
    },
    [clearItems, handleError, loadWorkspaceThreads, setStatus]
  );

  const selectThread = React.useCallback(
    async (threadId: string) => {
      if (threadId === currentThreadId) return;
      setCurrentThreadId(threadId);
      currentThreadRef.current = threadId;
      setModels(null);
      clearItems();
      await loadThreadHistory(threadId);
    },
    [clearItems, currentThreadId, loadThreadHistory]
  );

  const createThread = React.useCallback(async () => {
    if (!activeWorkspaceId) return null;
    try {
      const created = await createThreadRequest(activeWorkspaceId);
      setThreads((prev) => (prev.some((t) => t.id === created.id) ? prev : [created, ...prev]));
      setCurrentThreadId(created.id);
      currentThreadRef.current = created.id;
      setModels(null);
      clearItems();
      return created.id;
    } catch (error) {
      handleError(error, "Failed to create thread");
      return null;
    }
  }, [activeWorkspaceId, clearItems, handleError]);

  const deleteThread = React.useCallback(
    async (threadId: string) => {
      try {
        await deleteThreadRequest(threadId);
        const remaining = threads.filter((t) => t.id !== threadId);
        setThreads(remaining);
        if (threadId === currentThreadId) {
          if (remaining.length > 0) {
            setCurrentThreadId(remaining[0].id);
            currentThreadRef.current = remaining[0].id;
            await loadThreadHistory(remaining[0].id);
          } else if (activeWorkspaceId) {
            const created = await createThreadRequest(activeWorkspaceId);
            setThreads([created]);
            setCurrentThreadId(created.id);
            currentThreadRef.current = created.id;
            clearItems();
          }
        }
        setStatus("Thread deleted.");
      } catch (error) {
        handleError(error, "Failed to delete thread");
      }
    },
    [activeWorkspaceId, clearItems, currentThreadId, handleError, loadThreadHistory, setStatus, threads]
  );

  const clearThread = React.useCallback(
    async (threadId: string) => {
      try {
        await clearThreadRequest(threadId);
        if (threadId === currentThreadId) {
          clearItems();
        }
        setStatus("Thread cleared.");
      } catch (error) {
        handleError(error, "Failed to clear thread");
      }
    },
    [clearItems, currentThreadId, handleError, setStatus]
  );

  const loadAgentsList = React.useCallback(async () => {
    if (agents !== null) return;
    setIsLoadingAgents(true);
    try {
      const payload = await listAgents();
      setAgents(payload.agents);
      setDefaultAgentId(payload.defaultAgent);
    } catch (error) {
      handleError(error, "Failed to load agents");
    } finally {
      setIsLoadingAgents(false);
    }
  }, [agents, handleError]);

  const loadModelsList = React.useCallback(async () => {
    if (!currentThreadId || models !== null) return;
    setIsLoadingModels(true);
    try {
      const payload = await listThreadModels(currentThreadId);
      setModels(payload.models);
    } catch (error) {
      handleError(error, "Failed to load models");
    } finally {
      setIsLoadingModels(false);
    }
  }, [currentThreadId, handleError, models]);

  const selectAgent = React.useCallback(
    async (agentId: string | null) => {
      if (!currentThreadId) return;
      try {
        const updated = await updateThread(currentThreadId, { agent_id: agentId });
        setThreads((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
        setModels(null);
        setStatus(updated.resolved_agent.is_default ? "Agent reset to default." : "Agent updated.");
      } catch (error) {
        handleError(error, "Failed to update agent");
      }
    },
    [currentThreadId, handleError, setStatus]
  );

  const selectModel = React.useCallback(
    async (model: string | null) => {
      if (!currentThreadId) return;
      try {
        const updated = await updateThread(currentThreadId, { model });
        setThreads((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
        setStatus(updated.resolved_model.is_default ? "Model reset to default." : "Model updated.");
      } catch (error) {
        handleError(error, "Failed to update model");
      }
    },
    [currentThreadId, handleError, setStatus]
  );

  const sendMessage = React.useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!currentThreadId || !trimmed) return;
      try {
        const res = await startRun(currentThreadId, trimmed);
        upsertItem(res.user_item);
      } catch (error) {
        handleError(error, "Failed to start run");
      }
    },
    [currentThreadId, handleError, upsertItem]
  );

  const stopActiveRun = React.useCallback(async () => {
    const runId = currentThread?.active_run_id;
    if (!runId) return;
    try {
      await cancelRun(runId);
    } catch (error) {
      handleError(error, "Failed to cancel run");
    }
  }, [currentThread?.active_run_id, handleError]);

  const resolveApproval = React.useCallback(
    async (runId: string, approvalId: string, approved: boolean) => {
      try {
        const res = await resolveApprovalRequest(runId, approvalId, approved);
        upsertItem(res.approval_item);
      } catch (error) {
        handleError(error, "Failed to resolve approval");
      }
    },
    [handleError, upsertItem]
  );

  const submitAuthToken = React.useCallback((token: string) => {
    setAuthToken(token);
    setAuthError(null);
    setConnectionState("reconnecting");
    setAuthRevision((r) => r + 1);
  }, []);

  const signOut = React.useCallback(() => {
    setAuthToken(null);
    setConnectionState("auth_required");
    setAuthRevision((r) => r + 1);
  }, []);

  return {
    workspaces,
    activeWorkspace,
    activeWorkspaceId,
    threads,
    currentThread,
    currentThreadId,
    agents,
    defaultAgentId,
    models,
    activeAgentInfo,
    pluginState,
    isLoadingPluginState,
    gitStatus,
    isLoadingGitStatus,
    isLoadingThreads,
    isLoadingHistory,
    isLoadingAgents,
    isLoadingModels,
    statusMessage,
    connectionState,
    authError,
    refreshAll,
    refreshPluginState,
    refreshGitStatus,
    selectWorkspace,
    registerWorkspace,
    selectThread,
    createThread,
    deleteThread,
    clearThread,
    loadAgentsList,
    loadModelsList,
    selectAgent,
    selectModel,
    sendMessage,
    stopActiveRun,
    resolveApproval,
    submitAuthToken,
    signOut
  };
}

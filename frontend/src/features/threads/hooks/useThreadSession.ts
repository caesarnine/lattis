import React from "react";

import {
  bootstrapSession,
  createThread as createThreadRequest,
  getThreadState,
  listAgents,
  listThreadModels,
  listThreads,
  updateThreadState,
  type AgentInfo,
  type AgentSelection,
  type ModelSelection
} from "@/services/latticeApi";
import { type UiMessage } from "@/services/vercel";

const STATUS_TIMEOUT_MS = 2000;

type AgentState = {
  selectedId: string | null;
  selectedName: string | null;
  defaultId: string | null;
};

type ModelState = {
  selectedId: string | null;
  defaultId: string | null;
};

type UseThreadSessionParams = {
  hydrateMessages: (messages: UiMessage[]) => void;
  addSystemMessage: (content: string) => void;
};

function toNullable(value?: string | null) {
  return value && value.trim() ? value : null;
}

export function useThreadSession({
  hydrateMessages,
  addSystemMessage
}: UseThreadSessionParams) {
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [threads, setThreads] = React.useState<string[]>([]);
  const [currentThread, setCurrentThread] = React.useState<string | null>(null);
  const [agentState, setAgentState] = React.useState<AgentState>({
    selectedId: null,
    selectedName: null,
    defaultId: null
  });
  const [modelState, setModelState] = React.useState<ModelState>({
    selectedId: null,
    defaultId: null
  });
  const [agents, setAgents] = React.useState<AgentInfo[] | null>(null);
  const [models, setModels] = React.useState<string[] | null>(null);
  const [isLoadingThreads, setIsLoadingThreads] = React.useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = React.useState(false);
  const [isLoadingAgents, setIsLoadingAgents] = React.useState(false);
  const [isLoadingModels, setIsLoadingModels] = React.useState(false);
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const statusTimeout = React.useRef<number | null>(null);

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

  const applySelections = React.useCallback((
    agentSelection: AgentSelection,
    modelSelection: ModelSelection
  ) => {
    setAgentState({
      selectedId: toNullable(agentSelection.agent),
      selectedName: toNullable(agentSelection.agentName),
      defaultId: toNullable(agentSelection.defaultAgent)
    });
    setModelState({
      selectedId: toNullable(modelSelection.model),
      defaultId: toNullable(modelSelection.defaultModel)
    });
  }, []);

  const loadThreadState = React.useCallback(
    async (activeSessionId: string, threadId: string) => {
      setIsLoadingHistory(true);
      try {
        const state = await getThreadState(activeSessionId, threadId);
        applySelections(state.agent, state.model);
        setModels(null);
        hydrateMessages(state.messages);
      } catch (error) {
        addSystemMessage(
          `Failed to load history: ${
            error instanceof Error ? error.message : String(error)
          }`
        );
      } finally {
        setIsLoadingHistory(false);
      }
    },
    [addSystemMessage, applySelections, hydrateMessages]
  );

  const refreshThreads = React.useCallback(async () => {
    if (!sessionId) return;
    setIsLoadingThreads(true);
    try {
      const list = await listThreads(sessionId);
      setThreads(list);
      setStatus(null, 0);
      if (list.length && !currentThread) {
        setCurrentThread(list[0]);
        await loadThreadState(sessionId, list[0]);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to refresh threads", 0);
    } finally {
      setIsLoadingThreads(false);
    }
  }, [currentThread, loadThreadState, sessionId, setStatus]);

  const selectThread = React.useCallback(
    async (threadId: string) => {
      if (!sessionId || threadId === currentThread) return;
      setCurrentThread(threadId);
      await loadThreadState(sessionId, threadId);
    },
    [currentThread, loadThreadState, sessionId]
  );

  const createThread = React.useCallback(async () => {
    if (!sessionId) return null;
    try {
      const newThread = await createThreadRequest(sessionId);
      setThreads((prev) => [newThread, ...prev]);
      setCurrentThread(newThread);
      await loadThreadState(sessionId, newThread);
      setStatus(null, 0);
      return newThread;
    } catch (error) {
      setStatus(
        error instanceof Error ? error.message : "Failed to create thread",
        0
      );
      return null;
    }
  }, [loadThreadState, sessionId, setStatus]);

  const loadAgents = React.useCallback(async () => {
    if (agents !== null) return;
    setIsLoadingAgents(true);
    try {
      const payload = await listAgents();
      setAgents(payload.agents);
      setAgentState((prev) => ({
        ...prev,
        defaultId: prev.defaultId ?? toNullable(payload.defaultAgent)
      }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to load agents", 0);
    } finally {
      setIsLoadingAgents(false);
    }
  }, [agents, setStatus]);

  const loadModels = React.useCallback(async () => {
    if (!sessionId || !currentThread || models !== null) return;
    setIsLoadingModels(true);
    try {
      const payload = await listThreadModels(sessionId, currentThread);
      setModels(payload.models);
      setModelState((prev) => ({
        ...prev,
        defaultId: toNullable(payload.defaultModel)
      }));
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to load models", 0);
    } finally {
      setIsLoadingModels(false);
    }
  }, [currentThread, models, sessionId, setStatus]);

  const selectAgent = React.useCallback(
    async (nextAgent: string | null) => {
      if (!sessionId || !currentThread) return;
      try {
        const state = await updateThreadState(sessionId, currentThread, {
          agent: nextAgent
        });
        applySelections(state.agent, state.model);
        setModels(null);
        setStatus(state.agent.isDefault ? "Agent reset to default." : "Agent updated.");
      } catch (error) {
        setStatus(
          error instanceof Error ? error.message : "Failed to update agent",
          0
        );
      }
    },
    [applySelections, currentThread, sessionId, setStatus]
  );

  const selectModel = React.useCallback(
    async (nextModel: string | null) => {
      if (!sessionId || !currentThread) return;
      try {
        const state = await updateThreadState(sessionId, currentThread, {
          model: nextModel
        });
        applySelections(state.agent, state.model);
        setStatus(state.model.isDefault ? "Model reset to default." : "Model updated.");
      } catch (error) {
        setStatus(
          error instanceof Error ? error.message : "Failed to update model",
          0
        );
      }
    },
    [applySelections, currentThread, sessionId, setStatus]
  );

  React.useEffect(() => {
    let active = true;

    const init = async () => {
      try {
        setStatus("Connecting to server...", 0);
        const bootstrap = await bootstrapSession();
        if (!active) return;
        setSessionId(toNullable(bootstrap.sessionId));
        setThreads(bootstrap.threads);
        setCurrentThread(toNullable(bootstrap.threadId));
        applySelections(bootstrap.agent, bootstrap.model);
        setModels(null);
        hydrateMessages(bootstrap.messages);
        setStatus(null, 0);
      } catch (error) {
        if (!active) return;
        setStatus(
          error instanceof Error ? error.message : "Failed to start client",
          0
        );
      }
    };

    init();

    return () => {
      active = false;
    };
  }, [applySelections, hydrateMessages, setStatus]);

  return {
    sessionId,
    threads,
    currentThread,
    agentState,
    modelState,
    agents,
    models,
    isLoadingThreads,
    isLoadingHistory,
    isLoadingAgents,
    isLoadingModels,
    statusMessage,
    refreshThreads,
    selectThread,
    createThread,
    loadAgents,
    loadModels,
    selectAgent,
    selectModel
  };
}

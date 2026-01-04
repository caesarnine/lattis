import React from "react";
import { PanelLeft, Send, Square, ArrowDown, Sparkles } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import { cn } from "@/lib/utils";
import { ChatMessage } from "@/components/ChatMessage";
import { ToolCall } from "@/components/ToolCall";
import { ThreadSidebar } from "@/components/ThreadSidebar";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import {
  SERVER_URL,
  createThread,
  getThreadAgent,
  getSessionModel,
  getSessionId,
  listAgents,
  listModels,
  listThreads,
  getThreadMessages,
  runChatStream,
  setThreadAgent,
  setSessionModel,
  type AgentInfo
} from "@/lib/api";
import { createId } from "@/lib/ids";
import { useChatItems } from "@/hooks/useChatItems";

export default function App() {
  const [sessionId, setSessionId] = React.useState<string | null>(null);
  const [threads, setThreads] = React.useState<string[]>([]);
  const [currentThread, setCurrentThread] = React.useState<string | null>(null);
  const { items, addMessage, handleStreamEvent, hydrateUiMessages, resetMaps } =
    useChatItems();
  const [input, setInput] = React.useState("");
  const [isStreaming, setIsStreaming] = React.useState(false);
  const [agent, setAgent] = React.useState<string | null>(null);
  const [agentName, setAgentName] = React.useState<string | null>(null);
  const [defaultAgent, setDefaultAgent] = React.useState<string | null>(null);
  const [agents, setAgents] = React.useState<AgentInfo[] | null>(null);
  const [isLoadingAgents, setIsLoadingAgents] = React.useState(false);
  const [model, setModel] = React.useState<string | null>(null);
  const [defaultModel, setDefaultModel] = React.useState<string | null>(null);
  const [models, setModels] = React.useState<string[] | null>(null);
  const [isLoadingModels, setIsLoadingModels] = React.useState(false);
  const [isLoadingThreads, setIsLoadingThreads] = React.useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = React.useState(false);
  const [statusMessage, setStatusMessage] = React.useState<string | null>(null);
  const [isThreadPanelOpen, setIsThreadPanelOpen] = React.useState(false);
  const [showScrollButton, setShowScrollButton] = React.useState(false);

  const runAbort = React.useRef<AbortController | null>(null);
  const scrollRef = React.useRef<HTMLDivElement | null>(null);
  const modelLabel = model ?? defaultModel ?? "";
  const agentLabel = agentName ?? agent ?? defaultAgent ?? "";

  const scrollToBottom = React.useCallback(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth"
    });
  }, []);

  const handleScroll = React.useCallback((event: React.UIEvent<HTMLDivElement>) => {
    const target = event.currentTarget;
    const isAtBottom = target.scrollHeight - target.scrollTop <= target.clientHeight + 100;
    setShowScrollButton(!isAtBottom);
  }, []);

  React.useEffect(() => {
    if (!showScrollButton) {
      scrollToBottom();
    }
  }, [items, scrollToBottom, showScrollButton]);

  const loadThreads = React.useCallback(
    async (session: string) => {
      setIsLoadingThreads(true);
      try {
        const list = await listThreads(session);
        setThreads(list);
        return list;
      } finally {
        setIsLoadingThreads(false);
      }
    },
    []
  );

  const loadThreadHistory = React.useCallback(
    async (session: string, threadId: string) => {
      setIsLoadingHistory(true);
      try {
        const messages = await getThreadMessages(session, threadId);
        hydrateUiMessages(messages);
      } catch (error) {
        addMessage({
          id: createId("history-error"),
          role: "system",
          content: `Failed to load history: ${
            error instanceof Error ? error.message : String(error)
          }`
        });
      } finally {
        setIsLoadingHistory(false);
      }
    },
    [addMessage, hydrateUiMessages]
  );

  const loadThreadAgent = React.useCallback(async (session: string, threadId: string) => {
    const payload = await getThreadAgent(session, threadId);
    setAgent(payload.agent);
    setAgentName(payload.agentName || null);
    setDefaultAgent(payload.defaultAgent);
  }, []);

  const loadSessionModel = React.useCallback(async (session: string) => {
    const payload = await getSessionModel(session);
    setModel(payload.model);
    setDefaultModel(payload.defaultModel);
  }, []);

  const loadAgents = React.useCallback(async () => {
    if (agents && agents.length) {
      return;
    }
    setIsLoadingAgents(true);
    try {
      const payload = await listAgents();
      setAgents(payload.agents);
      setDefaultAgent((prev) => prev ?? payload.defaultAgent);
    } finally {
      setIsLoadingAgents(false);
    }
  }, [agents]);

  const loadModels = React.useCallback(async () => {
    if (models && models.length) {
      return;
    }
    setIsLoadingModels(true);
    try {
      const payload = await listModels();
      setModels(payload.models);
      setDefaultModel((prev) => prev ?? payload.defaultModel);
    } finally {
      setIsLoadingModels(false);
    }
  }, [models]);

  const handleSelectAgent = React.useCallback(
    async (nextAgent: string | null) => {
      if (!sessionId || !currentThread) return;
      try {
        const payload = await setThreadAgent(sessionId, currentThread, nextAgent);
        setAgent(payload.agent);
        setAgentName(payload.agentName || null);
        setDefaultAgent(payload.defaultAgent);
        setStatusMessage(payload.isDefault ? "Agent reset to default." : "Agent updated.");
        setTimeout(() => setStatusMessage(null), 2000);
        await loadSessionModel(sessionId);
      } catch (error) {
        setStatusMessage(
          error instanceof Error ? error.message : "Failed to update agent"
        );
      }
    },
    [currentThread, loadSessionModel, sessionId]
  );

  const handleSelectModel = React.useCallback(
    async (nextModel: string | null) => {
      if (!sessionId) return;
      try {
        const payload = await setSessionModel(sessionId, nextModel);
        setModel(payload.model);
        setDefaultModel(payload.defaultModel);
        setStatusMessage(payload.isDefault ? "Model reset to default." : "Model updated.");
        setTimeout(() => setStatusMessage(null), 2000);
      } catch (error) {
        setStatusMessage(
          error instanceof Error ? error.message : "Failed to update model"
        );
      }
    },
    [sessionId]
  );

  React.useEffect(() => {
    let active = true;

    const init = async () => {
      try {
        setStatusMessage("Connecting to server...");
        const session = await getSessionId();
        if (!active) return;
        setSessionId(session);
        await loadSessionModel(session);
        const list = await loadThreads(session);
        let threadId = list[0];
        if (!threadId) {
          threadId = await createThread(session);
          setThreads([threadId]);
        }
        if (!active) return;
        setCurrentThread(threadId);
        await loadThreadAgent(session, threadId);
        await loadThreadHistory(session, threadId);
        setStatusMessage(null);
      } catch (error) {
        if (!active) return;
        setStatusMessage(
          error instanceof Error ? error.message : "Failed to start client"
        );
      }
    };

    init();

    return () => {
      active = false;
      runAbort.current?.abort();
    };
  }, [loadSessionModel, loadThreadAgent, loadThreadHistory, loadThreads]);

  const handleSelectThread = async (threadId: string) => {
    if (!sessionId) return;
    if (threadId === currentThread) {
      setIsThreadPanelOpen(false);
      return;
    }
    runAbort.current?.abort();
    setIsThreadPanelOpen(false);
    setCurrentThread(threadId);
    await loadThreadAgent(sessionId, threadId);
    await loadThreadHistory(sessionId, threadId);
  };

  const handleCreateThread = async () => {
    if (!sessionId) return;
    try {
      const newThread = await createThread(sessionId);
      setThreads((prev) => [newThread, ...prev]);
      setCurrentThread(newThread);
      setIsThreadPanelOpen(false);
      await loadThreadAgent(sessionId, newThread);
      await loadThreadHistory(sessionId, newThread);
    } catch (error) {
      setStatusMessage(
        error instanceof Error ? error.message : "Failed to create thread"
      );
    }
  };

  const handleRefreshThreads = async () => {
    if (!sessionId) return;
    try {
      const list = await loadThreads(sessionId);
      if (list.length && !currentThread) {
        setCurrentThread(list[0]);
      }
    } catch (error) {
      setStatusMessage(
        error instanceof Error ? error.message : "Failed to refresh threads"
      );
    }
  };

  const handleSend = async () => {
    if (!sessionId || !currentThread) return;
    if (isStreaming) {
      handleStop();
      return;
    }
    const trimmed = input.trim();
    if (!trimmed) return;

    setInput("");
    addMessage({
      id: createId("user"),
      role: "user",
      content: trimmed
    });

    resetMaps();
    setIsStreaming(true);

    const controller = new AbortController();
    runAbort.current = controller;

    const payload = {
      trigger: "submit-message",
      id: createId("run"),
      messages: [
        {
          id: createId("msg"),
          role: "user",
          parts: [
            {
              type: "text",
              text: trimmed
            }
          ]
        }
      ],
      session_id: sessionId,
      thread_id: currentThread
    };

    try {
      const stream = await runChatStream(payload, controller.signal);
      for await (const event of stream) {
        handleStreamEvent(event);
      }
    } catch (error) {
      handleStop();
      if (!controller.signal.aborted) {
        addMessage({
          id: createId("run-error"),
          role: "system",
          content: `Run error: ${
            error instanceof Error ? error.message : String(error)
          }`
        });
      }
    } finally {
      setIsStreaming(false);
      runAbort.current = null;
    }
  };

  const handleStop = () => {
    if (runAbort.current) {
      runAbort.current.abort();
      setIsStreaming(false);
    }
  };

  const handleComposerKey = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="mobile-app-container relative bg-slate-50 md:bg-transparent">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-32 top-12 h-56 w-56 rounded-full bg-teal-200/40 blur-3xl" />
        <div className="absolute -right-32 top-48 h-72 w-72 rounded-full bg-orange-200/50 blur-3xl" />
      </div>

      <div className="relative mx-auto flex h-full w-full max-w-7xl flex-col md:flex-row md:gap-6 md:p-6">
        <div className="hidden md:block md:w-80">
            <ThreadSidebar
              threads={threads}
              currentThread={currentThread}
              onSelect={handleSelectThread}
              onCreate={handleCreateThread}
              onRefresh={handleRefreshThreads}
              isLoading={isLoadingThreads}
              sessionId={sessionId}
              serverUrl={SERVER_URL}
              agent={agent}
              agentName={agentName}
              defaultAgent={defaultAgent}
              agents={agents}
              isLoadingAgents={isLoadingAgents}
              onLoadAgents={loadAgents}
              onSelectAgent={handleSelectAgent}
              model={model}
              defaultModel={defaultModel}
              models={models}
              isLoadingModels={isLoadingModels}
              onLoadModels={loadModels}
              onSelectModel={handleSelectModel}
            />
          </div>

        <main className="flex min-w-0 min-h-0 flex-1 flex-col border-ink-200/70 bg-glass shadow-soft overflow-hidden md:rounded-3xl md:border">
          <header className="flex-none flex min-w-0 items-center justify-between gap-4 px-4 py-5 md:px-6">
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.3em] text-ink-500">
                Active Thread
              </div>
              <div className="text-xl font-display text-ink-900 truncate max-w-[250px] md:max-w-none">
                {currentThread ?? ""}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                className="md:hidden"
                onClick={() => setIsThreadPanelOpen(true)}
              >
                <PanelLeft size={16} />
                Threads
              </Button>
              <span className="rounded-full border border-ink-200 bg-white/80 px-4 py-2 text-xs font-semibold uppercase tracking-widest text-ink-600">
                {isStreaming ? "Streaming" : "Idle"}
              </span>
              {agentLabel ? (
                <span
                  title={agentLabel}
                  className="max-w-[220px] truncate rounded-full border border-ink-200 bg-white/70 px-4 py-2 text-[11px] font-semibold text-ink-600"
                >
                  Agent: {agentLabel}
                </span>
              ) : null}
              {modelLabel ? (
                <span
                  title={modelLabel}
                  className="max-w-[220px] truncate rounded-full border border-ink-200 bg-white/70 px-4 py-2 text-[11px] font-semibold text-ink-600"
                >
                  Model: {modelLabel}
                </span>
              ) : null}
              {statusMessage ? (
                <span className="text-xs text-ink-500">{statusMessage}</span>
              ) : null}
            </div>
          </header>

          <Separator />

          <ScrollArea 
            className="flex-1 min-w-0 min-h-0 relative touch-pan-y" 
            viewportRef={scrollRef}
            onScroll={handleScroll}
          >
            <div className="flex w-full min-w-0 min-h-full flex-col gap-3 p-4 md:gap-4 md:p-6">
              {items.length === 0 && !isLoadingHistory ? (
                <div className="flex flex-col items-center justify-center flex-1 py-12 px-4 text-center">
                  <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-3xl bg-teal-50 text-teal-600 shadow-sm border border-teal-100">
                    <Sparkles size={32} />
                  </div>
                  <h3 className="mb-2 text-xl font-display text-ink-900">
                    {agentName ? `Meet ${agentName}` : "Meet your agent"}
                  </h3>
                  <p className="max-w-xs text-sm text-ink-500 leading-relaxed">
                    Your personal agent for building toolkits and automating tasks. How can I help you today?
                  </p>
                </div>
              ) : null}

              {isLoadingHistory ? (
                <div className="rounded-3xl border border-dashed border-ink-200 bg-white/60 p-8 text-center text-sm text-ink-500">
                  Loading thread history…
                </div>
              ) : null}

              <AnimatePresence>
                {showScrollButton && (
                  <motion.button
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 10 }}
                    onClick={scrollToBottom}
                    className="fixed bottom-32 right-8 z-50 flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-lg border border-ink-200 text-ink-600 hover:bg-ink-50 md:bottom-36 md:right-12"
                  >
                    <ArrowDown size={18} />
                  </motion.button>
                )}
              </AnimatePresence>

              {items.map((item) => {
                if (item.kind === "message") {
                  const isUser = item.role === "user";
                  return (
                    <div
                      key={item.id}
                      className={`flex w-full min-w-0 ${isUser ? "justify-end" : "justify-start"}`}
                    >
                      <ChatMessage
                        role={item.role}
                        content={item.content}
                        className="max-w-[98%] md:max-w-[85%]"
                      />
                    </div>
                  );
                }

                return (
                  <div key={item.id} className="flex w-full min-w-0 justify-start">
                    <ToolCall
                      toolName={item.toolName}
                      argsRaw={item.argsRaw}
                      result={item.result}
                      className="max-w-[98%] md:max-w-[85%]"
                    />
                  </div>
                );
              })}
            </div>
          </ScrollArea>

          <Separator />

          <div className="flex-none px-4 py-4 pb-8 md:px-6 md:pb-6">
            <div className="relative flex flex-col gap-2 rounded-[2rem] border border-ink-200/80 bg-white p-2 shadow-soft transition-all focus-within:border-teal-400/50 focus-within:shadow-glow">
              <Textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleComposerKey}
                className="min-h-[60px] resize-none border-0 bg-transparent px-4 py-3 text-base shadow-none focus-visible:ring-0 md:text-sm touch-manipulation"
                placeholder={agentName ? `Message ${agentName}...` : "Message the agent..."}
                style={{ fontSize: "16px" }}
              />
              <div className="flex items-center justify-between px-2 pb-1">
                <div className="text-[10px] font-medium text-ink-400 px-3 uppercase tracking-widest desktop-hint">
                  Shift+Enter for newline
                </div>
                <Button 
                  onClick={handleSend} 
                  disabled={!isStreaming && !input.trim()}
                  size="sm"
                  className={cn(
                    "h-10 rounded-full px-5 transition-all shadow-sm",
                    isStreaming 
                      ? "bg-rose-50 text-rose-600 hover:bg-rose-100 border border-rose-200" 
                      : "bg-ink-900 text-white hover:bg-ink-800"
                  )}
                >
                  {isStreaming ? (
                    <>
                      <Square size={14} className="fill-current" />
                      <span className="ml-2 font-semibold">Stop</span>
                    </>
                  ) : (
                    <>
                      <Send size={14} />
                      <span className="ml-2 font-semibold text-xs">Send</span>
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>
        </main>
      </div>

      {isThreadPanelOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <div
            className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm"
            onClick={() => setIsThreadPanelOpen(false)}
          />
          <div className="absolute inset-x-0 bottom-0 top-0">
            <ThreadSidebar
              threads={threads}
              currentThread={currentThread}
              onSelect={handleSelectThread}
              onCreate={handleCreateThread}
              onRefresh={handleRefreshThreads}
              isLoading={isLoadingThreads}
              sessionId={sessionId}
              serverUrl={SERVER_URL}
              agent={agent}
              agentName={agentName}
              defaultAgent={defaultAgent}
              agents={agents}
              isLoadingAgents={isLoadingAgents}
              onLoadAgents={loadAgents}
              onSelectAgent={handleSelectAgent}
              model={model}
              defaultModel={defaultModel}
              models={models}
              isLoadingModels={isLoadingModels}
              onLoadModels={loadModels}
              onSelectModel={handleSelectModel}
              onClose={() => setIsThreadPanelOpen(false)}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

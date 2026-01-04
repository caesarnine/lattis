import React from "react";

import { ChatPanel } from "@/features/chat/components/ChatPanel";
import { useAutoScroll } from "@/features/chat/hooks/useAutoScroll";
import { useChatItems } from "@/features/chat/hooks/useChatItems";
import { useChatStream } from "@/features/chat/hooks/useChatStream";
import { ThreadPanel } from "@/features/threads/components/ThreadPanel";
import { useThreadSession } from "@/features/threads/hooks/useThreadSession";
import { SERVER_URL } from "@/services/latticeApi";

export default function App() {
  const [isThreadPanelOpen, setIsThreadPanelOpen] = React.useState(false);

  const { items, addMessage, addSystemMessage, handleStreamEvent, hydrateUiMessages } =
    useChatItems();

  const {
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
  } = useThreadSession({
    hydrateMessages: hydrateUiMessages,
    addSystemMessage
  });

  const { isStreaming, sendMessage, stop } = useChatStream({
    sessionId,
    threadId: currentThread,
    addMessage,
    onStreamEvent: handleStreamEvent
  });

  const { scrollRef, showScrollButton, scrollToBottom, handleScroll } =
    useAutoScroll(items.length);

  const agentLabel =
    agentState.selectedName ?? agentState.selectedId ?? agentState.defaultId ?? "";
  const modelLabel = modelState.selectedId ?? modelState.defaultId ?? "";
  const canSend = Boolean(sessionId && currentThread);

  const handleSelectThread = async (threadId: string) => {
    if (threadId === currentThread) {
      setIsThreadPanelOpen(false);
      return;
    }
    stop();
    await selectThread(threadId);
    setIsThreadPanelOpen(false);
  };

  const handleCreateThread = async () => {
    const newThread = await createThread();
    if (newThread) {
      setIsThreadPanelOpen(false);
    }
  };

  const threadSidebarProps = {
    threads: {
      list: threads,
      current: currentThread,
      isLoading: isLoadingThreads,
      onSelect: handleSelectThread,
      onCreate: handleCreateThread,
      onRefresh: refreshThreads
    },
    agents: {
      selectedId: agentState.selectedId,
      selectedName: agentState.selectedName,
      defaultId: agentState.defaultId,
      list: agents,
      isLoading: isLoadingAgents,
      onLoad: loadAgents,
      onSelect: selectAgent
    },
    models: {
      selectedId: modelState.selectedId,
      defaultId: modelState.defaultId,
      list: models,
      isLoading: isLoadingModels,
      onLoad: loadModels,
      onSelect: selectModel
    },
    session: {
      id: sessionId,
      serverUrl: SERVER_URL
    }
  };

  return (
    <div className="mobile-app-container relative bg-slate-50 md:bg-transparent">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-32 top-12 h-56 w-56 rounded-full bg-teal-200/40 blur-3xl" />
        <div className="absolute -right-32 top-48 h-72 w-72 rounded-full bg-orange-200/50 blur-3xl" />
      </div>

      <div className="relative mx-auto flex h-full w-full max-w-7xl flex-col md:flex-row md:gap-6 md:p-6">
        <ThreadPanel
          isOpen={isThreadPanelOpen}
          onClose={() => setIsThreadPanelOpen(false)}
          sidebarProps={threadSidebarProps}
        />

        <ChatPanel
          currentThread={currentThread}
          agentName={agentState.selectedName}
          agentLabel={agentLabel}
          modelLabel={modelLabel}
          statusMessage={statusMessage}
          isStreaming={isStreaming}
          items={items}
          isLoadingHistory={isLoadingHistory}
          canSend={canSend}
          onSend={sendMessage}
          onStop={stop}
          onOpenThreads={() => setIsThreadPanelOpen(true)}
          scrollRef={scrollRef}
          onScroll={handleScroll}
          showScrollButton={showScrollButton}
          onScrollToBottom={scrollToBottom}
        />
      </div>
    </div>
  );
}

import React from "react";

import { ChatPanel } from "@/features/chat/components/ChatPanel";
import { useAutoScroll } from "@/features/chat/hooks/useAutoScroll";
import { useChatItems } from "@/features/chat/hooks/useChatItems";
import { AuthPrompt } from "@/features/threads/components/AuthPrompt";
import { ThreadPanel } from "@/features/threads/components/ThreadPanel";
import { useDaemonWorkspace } from "@/features/threads/hooks/useDaemonWorkspace";
import {
  WorkspaceInspector,
  type InspectorTab
} from "@/features/workspace/components/WorkspaceInspector";
import { getAuthToken, SERVER_URL } from "@/services/lattisClient";

export default function App() {
  const [isThreadPanelOpen, setIsThreadPanelOpen] = React.useState(false);
  const [isInspectorOpen, setIsInspectorOpen] = React.useState(false);
  const [inspectorTab, setInspectorTab] = React.useState<InspectorTab>("files");

  const {
    items,
    clearItems,
    addSystemMessage,
    upsertItem,
    hydrateItems,
    handleThreadEvent
  } = useChatItems();

  const {
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
  } = useDaemonWorkspace({
    hydrateItems,
    upsertItem,
    clearItems,
    onThreadEvent: handleThreadEvent,
    addSystemMessage
  });

  const { scrollRef, showScrollButton, scrollToBottom, handleScroll } =
    useAutoScroll(items.length);

  if (connectionState === "auth_required") {
    return (
      <AuthPrompt
        serverUrl={SERVER_URL}
        errorMessage={authError}
        onSubmit={submitAuthToken}
      />
    );
  }

  const agentName = currentThread?.resolved_agent.agent_name ?? null;
  const agentLabel =
    agentName ?? currentThread?.resolved_agent.agent ?? defaultAgentId ?? "";
  const modelLabel =
    currentThread?.resolved_model.model ??
    currentThread?.resolved_model.default_model ??
    "";
  const threadStatus = currentThread?.status ?? "idle";
  const isStreaming = threadStatus === "running";
  const canSend = Boolean(currentThreadId) && threadStatus === "idle";
  const hasPluginState = Boolean(activeAgentInfo?.has_state);
  const changedFileCount = gitStatus?.files?.length ?? 0;

  const handleSelectThread = async (threadId: string) => {
    await selectThread(threadId);
    setIsThreadPanelOpen(false);
  };

  const handleCreateThread = async () => {
    const created = await createThread();
    if (created) {
      setIsThreadPanelOpen(false);
    }
  };

  const threadSidebarProps = {
    workspaces: {
      list: workspaces,
      activeId: activeWorkspaceId,
      onSelect: selectWorkspace,
      onRegister: registerWorkspace
    },
    threads: {
      list: threads,
      currentId: currentThreadId,
      isLoading: isLoadingThreads,
      onSelect: handleSelectThread,
      onCreate: handleCreateThread,
      onClear: clearThread,
      onDelete: deleteThread,
      onRefresh: refreshAll
    },
    agents: {
      selectedId: currentThread?.resolved_agent.agent ?? null,
      selectedName: agentName,
      defaultId: currentThread?.resolved_agent.default_agent ?? defaultAgentId,
      list: agents,
      isLoading: isLoadingAgents,
      onLoad: loadAgentsList,
      onSelect: selectAgent
    },
    models: {
      selectedId: currentThread?.resolved_model.model ?? null,
      defaultId: currentThread?.resolved_model.default_model ?? null,
      list: models,
      isLoading: isLoadingModels,
      onLoad: loadModelsList,
      onSelect: selectModel
    },
    daemon: {
      serverUrl: SERVER_URL,
      connectionState,
      onSignOut: getAuthToken() ? signOut : undefined
    }
  };

  return (
    <div className="mobile-app-container relative bg-slate-50 md:bg-transparent">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -left-32 top-12 h-56 w-56 rounded-full bg-teal-200/40 blur-3xl" />
        <div className="absolute -right-32 top-48 h-72 w-72 rounded-full bg-orange-200/50 blur-3xl" />
      </div>

      <div className="relative mx-auto flex h-full w-full max-w-[1600px] flex-col md:flex-row md:gap-5 md:p-5">
        <ThreadPanel
          isOpen={isThreadPanelOpen}
          onClose={() => setIsThreadPanelOpen(false)}
          sidebarProps={threadSidebarProps}
        />

        <ChatPanel
          currentThreadId={currentThreadId}
          threadTitle={currentThread?.title || currentThreadId || ""}
          workspaceName={activeWorkspace?.name ?? ""}
          threadStatus={threadStatus}
          agentName={agentName}
          agentLabel={agentLabel}
          modelLabel={modelLabel}
          statusMessage={statusMessage}
          isStreaming={isStreaming}
          items={items}
          isLoadingHistory={isLoadingHistory}
          canSend={canSend}
          changedFileCount={changedFileCount}
          isInspectorOpen={isInspectorOpen}
          onToggleInspector={() => setIsInspectorOpen((open) => !open)}
          onSend={sendMessage}
          onStop={stopActiveRun}
          onResolveApproval={resolveApproval}
          onOpenThreads={() => setIsThreadPanelOpen(true)}
          scrollRef={scrollRef}
          onScroll={handleScroll}
          showScrollButton={showScrollButton}
          onScrollToBottom={scrollToBottom}
        />

        {isInspectorOpen ? (
          <div className="hidden md:block">
            <WorkspaceInspector
              workspaceId={activeWorkspaceId}
              workspaceName={activeWorkspace?.name ?? ""}
              agentName={agentLabel || "Plugin"}
              hasPluginState={hasPluginState}
              pluginState={pluginState}
              isLoadingPluginState={isLoadingPluginState}
              gitStatus={gitStatus}
              isLoadingGitStatus={isLoadingGitStatus}
              activeTab={inspectorTab}
              onTabChange={setInspectorTab}
              onRefreshPluginState={refreshPluginState}
              onRefreshGitStatus={refreshGitStatus}
              onClose={() => setIsInspectorOpen(false)}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}

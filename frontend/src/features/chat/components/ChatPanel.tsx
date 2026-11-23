import type { RefObject, UIEvent } from "react";

import { ChatComposer } from "@/features/chat/components/ChatComposer";
import { ChatHeader } from "@/features/chat/components/ChatHeader";
import { ChatMessageList } from "@/features/chat/components/ChatMessageList";
import { type RenderItem } from "@/features/chat/types";
import { Separator } from "@/shared/ui/separator";

type ChatPanelProps = {
  currentThreadId: string | null;
  threadTitle: string;
  workspaceName: string;
  threadStatus: "idle" | "running" | "waiting_approval";
  agentName: string | null;
  agentLabel: string;
  modelLabel: string;
  statusMessage: string | null;
  isStreaming: boolean;
  items: RenderItem[];
  isLoadingHistory: boolean;
  canSend: boolean;
  changedFileCount: number;
  isInspectorOpen: boolean;
  onToggleInspector: () => void;
  onSend: (message: string) => void;
  onStop: () => void;
  onResolveApproval: (runId: string, approvalId: string, approved: boolean) => Promise<void> | void;
  onOpenThreads: () => void;
  scrollRef: RefObject<HTMLDivElement>;
  onScroll: (event: UIEvent<HTMLDivElement>) => void;
  showScrollButton: boolean;
  onScrollToBottom: () => void;
};

export function ChatPanel({
  currentThreadId,
  threadTitle,
  workspaceName,
  threadStatus,
  agentName,
  agentLabel,
  modelLabel,
  statusMessage,
  isStreaming,
  items,
  isLoadingHistory,
  canSend,
  changedFileCount,
  isInspectorOpen,
  onToggleInspector,
  onSend,
  onStop,
  onResolveApproval,
  onOpenThreads,
  scrollRef,
  onScroll,
  showScrollButton,
  onScrollToBottom
}: ChatPanelProps) {
  return (
    <main className="flex min-w-0 min-h-0 flex-1 flex-col border-ink-200/70 bg-glass shadow-soft overflow-hidden md:rounded-3xl md:border">
      <ChatHeader
        threadTitle={threadTitle}
        workspaceName={workspaceName}
        threadStatus={threadStatus}
        agentLabel={agentLabel}
        modelLabel={modelLabel}
        statusMessage={statusMessage}
        changedFileCount={changedFileCount}
        isInspectorOpen={isInspectorOpen}
        onToggleInspector={onToggleInspector}
        onOpenThreads={onOpenThreads}
      />

      <Separator />

      <ChatMessageList
        items={items}
        isLoadingHistory={isLoadingHistory}
        agentName={agentName}
        onResolveApproval={onResolveApproval}
        scrollRef={scrollRef}
        onScroll={onScroll}
        showScrollButton={showScrollButton}
        onScrollToBottom={onScrollToBottom}
      />

      <Separator />

      <ChatComposer
        onSend={onSend}
        onStop={onStop}
        isStreaming={isStreaming}
        agentName={agentName}
        canSend={canSend}
        resetKey={currentThreadId}
      />
    </main>
  );
}

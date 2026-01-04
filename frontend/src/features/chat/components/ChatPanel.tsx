import type { RefObject, UIEvent } from "react";

import { ChatComposer } from "@/features/chat/components/ChatComposer";
import { ChatHeader } from "@/features/chat/components/ChatHeader";
import { ChatMessageList } from "@/features/chat/components/ChatMessageList";
import { type RenderItem } from "@/features/chat/types";
import { Separator } from "@/shared/ui/separator";

type ChatPanelProps = {
  currentThread: string | null;
  agentName: string | null;
  agentLabel: string;
  modelLabel: string;
  statusMessage: string | null;
  isStreaming: boolean;
  items: RenderItem[];
  isLoadingHistory: boolean;
  canSend: boolean;
  onSend: (message: string) => void;
  onStop: () => void;
  onOpenThreads: () => void;
  scrollRef: RefObject<HTMLDivElement>;
  onScroll: (event: UIEvent<HTMLDivElement>) => void;
  showScrollButton: boolean;
  onScrollToBottom: () => void;
};

export function ChatPanel({
  currentThread,
  agentName,
  agentLabel,
  modelLabel,
  statusMessage,
  isStreaming,
  items,
  isLoadingHistory,
  canSend,
  onSend,
  onStop,
  onOpenThreads,
  scrollRef,
  onScroll,
  showScrollButton,
  onScrollToBottom
}: ChatPanelProps) {
  return (
    <main className="flex min-w-0 min-h-0 flex-1 flex-col border-ink-200/70 bg-glass shadow-soft overflow-hidden md:rounded-3xl md:border">
      <ChatHeader
        currentThread={currentThread}
        isStreaming={isStreaming}
        agentLabel={agentLabel}
        modelLabel={modelLabel}
        statusMessage={statusMessage}
        onOpenThreads={onOpenThreads}
      />

      <Separator />

      <ChatMessageList
        items={items}
        isLoadingHistory={isLoadingHistory}
        agentName={agentName}
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
        resetKey={currentThread}
      />
    </main>
  );
}

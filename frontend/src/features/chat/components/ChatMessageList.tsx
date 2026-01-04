import type { RefObject, UIEvent } from "react";
import { ArrowDown, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { ChatMessage } from "@/features/chat/components/ChatMessage";
import { ToolCall } from "@/features/chat/components/ToolCall";
import { type RenderItem } from "@/features/chat/types";
import { ScrollArea } from "@/shared/ui/scroll-area";

type ChatMessageListProps = {
  items: RenderItem[];
  isLoadingHistory: boolean;
  agentName: string | null;
  scrollRef: RefObject<HTMLDivElement>;
  onScroll: (event: UIEvent<HTMLDivElement>) => void;
  showScrollButton: boolean;
  onScrollToBottom: () => void;
};

export function ChatMessageList({
  items,
  isLoadingHistory,
  agentName,
  scrollRef,
  onScroll,
  showScrollButton,
  onScrollToBottom
}: ChatMessageListProps) {
  return (
    <ScrollArea
      className="flex-1 min-w-0 min-h-0 relative touch-pan-y"
      viewportRef={scrollRef}
      onScroll={onScroll}
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
              Your personal agent for building toolkits and automating tasks. How
              can I help you today?
            </p>
          </div>
        ) : null}

        {isLoadingHistory ? (
          <div className="rounded-3xl border border-dashed border-ink-200 bg-white/60 p-8 text-center text-sm text-ink-500">
            Loading thread history…
          </div>
        ) : null}

        <AnimatePresence>
          {showScrollButton ? (
            <motion.button
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 10 }}
              onClick={onScrollToBottom}
              className="fixed bottom-32 right-8 z-50 flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-lg border border-ink-200 text-ink-600 hover:bg-ink-50 md:bottom-36 md:right-12"
            >
              <ArrowDown size={18} />
            </motion.button>
          ) : null}
        </AnimatePresence>

        {items.map((item) => {
          if (item.kind === "message") {
            const isUser = item.role === "user";
            return (
              <div
                key={item.id}
                className={`flex w-full min-w-0 ${
                  isUser ? "justify-end" : "justify-start"
                }`}
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
  );
}

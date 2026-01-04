import React from "react";
import { Send, Square } from "lucide-react";

import { cn } from "@/shared/utils";
import { Button } from "@/shared/ui/button";
import { Textarea } from "@/shared/ui/textarea";

type ChatComposerProps = {
  onSend: (message: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  agentName: string | null;
  canSend: boolean;
  resetKey?: string | null;
};

export function ChatComposer({
  onSend,
  onStop,
  isStreaming,
  agentName,
  canSend,
  resetKey
}: ChatComposerProps) {
  const [input, setInput] = React.useState("");

  React.useEffect(() => {
    setInput("");
  }, [resetKey]);

  const handleSubmit = () => {
    if (!canSend) return;
    const trimmed = input.trim();
    if (!trimmed || isStreaming) return;
    setInput("");
    onSend(trimmed);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (isStreaming) {
        onStop();
      } else if (canSend) {
        handleSubmit();
      }
    }
  };

  return (
    <div className="flex-none px-4 py-4 pb-8 md:px-6 md:pb-6">
      <div className="relative flex flex-col gap-2 rounded-[2rem] border border-ink-200/80 bg-white p-2 shadow-soft transition-all focus-within:border-teal-400/50 focus-within:shadow-glow">
        <Textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          className="min-h-[60px] resize-none border-0 bg-transparent px-4 py-3 text-base shadow-none focus-visible:ring-0 md:text-sm touch-manipulation"
          placeholder={agentName ? `Message ${agentName}...` : "Message the agent..."}
          style={{ fontSize: "16px" }}
        />
        <div className="flex items-center justify-between px-2 pb-1">
          <div className="text-[10px] font-medium text-ink-400 px-3 uppercase tracking-widest desktop-hint">
            Shift+Enter for newline
          </div>
          <Button
            onClick={isStreaming ? onStop : handleSubmit}
            disabled={!isStreaming && (!canSend || !input.trim())}
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
  );
}

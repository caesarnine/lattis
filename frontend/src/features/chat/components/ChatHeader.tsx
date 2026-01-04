import { PanelLeft } from "lucide-react";

import { Button } from "@/shared/ui/button";

type ChatHeaderProps = {
  currentThread: string | null;
  isStreaming: boolean;
  agentLabel: string;
  modelLabel: string;
  statusMessage: string | null;
  onOpenThreads: () => void;
};

export function ChatHeader({
  currentThread,
  isStreaming,
  agentLabel,
  modelLabel,
  statusMessage,
  onOpenThreads
}: ChatHeaderProps) {
  return (
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
          onClick={onOpenThreads}
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
  );
}

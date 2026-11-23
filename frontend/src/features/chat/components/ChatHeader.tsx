import { PanelLeft, PanelRight } from "lucide-react";

import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/utils";

type ChatHeaderProps = {
  threadTitle: string;
  workspaceName: string;
  threadStatus: "idle" | "running" | "waiting_approval";
  agentLabel: string;
  modelLabel: string;
  statusMessage: string | null;
  changedFileCount: number;
  isInspectorOpen: boolean;
  onToggleInspector: () => void;
  onOpenThreads: () => void;
};

export function ChatHeader({
  threadTitle,
  workspaceName,
  threadStatus,
  agentLabel,
  modelLabel,
  statusMessage,
  changedFileCount,
  isInspectorOpen,
  onToggleInspector,
  onOpenThreads
}: ChatHeaderProps) {
  const statusLabel =
    threadStatus === "running"
      ? "Running"
      : threadStatus === "waiting_approval"
        ? "Approval"
        : "Idle";

  return (
    <header className="flex-none flex min-w-0 items-center justify-between gap-4 px-4 py-4 md:px-6">
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.25em] text-ink-500 truncate">
          {workspaceName || "Workspace"}
        </div>
        <div className="text-xl font-display text-ink-900 truncate max-w-[240px] md:max-w-md">
          {threadTitle || "Untitled Thread"}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 md:gap-3">
        <Button
          variant="outline"
          size="sm"
          className="md:hidden"
          onClick={onOpenThreads}
        >
          <PanelLeft size={16} />
          Threads
        </Button>
        <span
          className={cn(
            "rounded-full border px-3 py-1.5 text-[11px] font-semibold uppercase tracking-widest",
            threadStatus === "running"
              ? "border-teal-300 bg-teal-50 text-teal-700"
              : threadStatus === "waiting_approval"
                ? "border-amber-300 bg-amber-50 text-amber-800"
                : "border-ink-200 bg-white/80 text-ink-600"
          )}
        >
          {statusLabel}
        </span>
        {!isInspectorOpen && agentLabel ? (
          <span
            title={agentLabel}
            className="hidden xl:inline-block max-w-[160px] truncate rounded-full border border-ink-200 bg-white/70 px-3 py-1.5 text-[11px] font-semibold text-ink-600"
          >
            {agentLabel}
          </span>
        ) : null}
        {!isInspectorOpen && modelLabel ? (
          <span
            title={modelLabel}
            className="hidden 2xl:inline-block max-w-[200px] truncate rounded-full border border-ink-200 bg-white/70 px-3 py-1.5 text-[11px] font-semibold text-ink-600"
          >
            {modelLabel}
          </span>
        ) : null}
        <Button
          variant={isInspectorOpen ? "default" : "outline"}
          size="sm"
          className="rounded-full"
          onClick={onToggleInspector}
        >
          <PanelRight size={14} className="mr-1.5" />
          Inspector
          {changedFileCount > 0 ? (
            <span
              className={cn(
                "ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none",
                isInspectorOpen
                  ? "bg-white/20 text-white"
                  : "bg-teal-100 text-teal-800"
              )}
            >
              {changedFileCount}
            </span>
          ) : null}
        </Button>
        {statusMessage ? (
          <span className="hidden sm:inline text-xs text-ink-500">{statusMessage}</span>
        ) : null}
      </div>
    </header>
  );
}

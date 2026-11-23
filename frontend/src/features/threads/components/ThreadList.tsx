import { Eraser, Trash2 } from "lucide-react";

import { type Thread } from "@/services/lattisClient";
import { cn } from "@/shared/utils";

type ThreadListProps = {
  threads: Thread[];
  currentThreadId: string | null;
  onSelect: (threadId: string) => void;
  onClear: (threadId: string) => void;
  onDelete: (threadId: string) => void;
};

export function ThreadList({
  threads,
  currentThreadId,
  onSelect,
  onClear,
  onDelete
}: ThreadListProps) {
  if (threads.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-ink-200 bg-white/40 p-4 text-sm text-ink-500">
        No threads yet. Create one to get started.
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      {threads.map((thread) => {
        const isActive = thread.id === currentThreadId;
        const displayTitle = thread.title?.trim() || thread.id;
        return (
          <div
            key={thread.id}
            className={cn(
              "group flex w-full items-center justify-between gap-2 rounded-2xl border px-3 py-2.5 text-left text-sm transition-all duration-150",
              isActive
                ? "border-teal-500/50 bg-teal-50 shadow-sm text-teal-900"
                : "border-transparent bg-white/40 text-ink-700 hover:bg-white/75 hover:text-ink-900"
            )}
          >
            <button
              type="button"
              onClick={() => onSelect(thread.id)}
              className="flex min-w-0 flex-1 items-center gap-2 text-left"
            >
              <span
                className={cn(
                  "h-2 w-2 shrink-0 rounded-full",
                  thread.status === "running"
                    ? "bg-teal-500 animate-pulse"
                    : thread.status === "waiting_approval"
                      ? "bg-amber-500 animate-pulse"
                      : isActive
                        ? "bg-teal-400/70"
                        : "bg-ink-300"
                )}
                title={thread.status}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-semibold">{displayTitle}</div>
                <div className="truncate text-[10px] text-ink-400">
                  {thread.resolved_agent.agent_name} · {thread.id}
                </div>
              </div>
            </button>

            <div className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
              <button
                type="button"
                title="Clear thread messages"
                onClick={(event) => {
                  event.stopPropagation();
                  onClear(thread.id);
                }}
                className="rounded-lg p-1 text-ink-400 hover:bg-white hover:text-ink-700"
              >
                <Eraser size={13} />
              </button>
              <button
                type="button"
                title="Delete thread"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(thread.id);
                }}
                className="rounded-lg p-1 text-ink-400 hover:bg-rose-50 hover:text-rose-600"
              >
                <Trash2 size={13} />
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

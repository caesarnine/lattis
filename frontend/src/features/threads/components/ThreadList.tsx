import { Badge } from "@/shared/ui/badge";
import { cn } from "@/shared/utils";

type ThreadListProps = {
  threads: string[];
  currentThread: string | null;
  onSelect: (threadId: string) => void;
};

export function ThreadList({ threads, currentThread, onSelect }: ThreadListProps) {
  if (threads.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-ink-200 bg-white/40 p-4 text-sm text-ink-500">
        No threads yet. Create one to get started.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {threads.map((thread) => (
        <button
          key={thread}
          onClick={() => onSelect(thread)}
          className={cn(
            "flex w-full items-center justify-between rounded-2xl border px-4 py-3 text-left text-sm transition-all duration-200",
            thread === currentThread
              ? "border-teal-500/50 bg-teal-50 shadow-sm text-teal-900"
              : "border-transparent bg-white/40 text-ink-600 hover:bg-white/70 hover:text-ink-900"
          )}
        >
          <span className="truncate font-semibold">{thread}</span>
          {thread === currentThread ? (
            <Badge variant="accent" className="text-[10px] uppercase">
              Active
            </Badge>
          ) : null}
        </button>
      ))}
    </div>
  );
}

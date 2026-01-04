import { Badge } from "@/shared/ui/badge";

type ThreadSidebarFooterProps = {
  sessionId?: string | null;
  serverUrl?: string;
  isLoading?: boolean;
};

export function ThreadSidebarFooter({
  sessionId,
  serverUrl,
  isLoading
}: ThreadSidebarFooterProps) {
  return (
    <div className="space-y-2 px-5 pb-5 pt-4 text-xs text-ink-500">
      <div className="flex flex-wrap items-center gap-2">
        <span className="uppercase tracking-widest">Session</span>
        <Badge variant="default" className="text-[10px]">
          {sessionId ? `${sessionId.slice(0, 6)}…${sessionId.slice(-4)}` : "-"}
        </Badge>
      </div>
      <div className="text-[11px] text-ink-400">{serverUrl ?? ""}</div>
      {isLoading ? (
        <div className="text-[11px] text-ink-500">Loading threads…</div>
      ) : null}
    </div>
  );
}

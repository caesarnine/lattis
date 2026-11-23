import { LogOut } from "lucide-react";

import { cn } from "@/shared/utils";

type ThreadSidebarFooterProps = {
  serverUrl?: string;
  connectionState: "connected" | "reconnecting" | "auth_required" | "error";
  isLoading?: boolean;
  onSignOut?: () => void;
};

export function ThreadSidebarFooter({
  serverUrl,
  connectionState,
  isLoading,
  onSignOut
}: ThreadSidebarFooterProps) {
  const statusDot =
    connectionState === "connected"
      ? "bg-emerald-500"
      : connectionState === "reconnecting"
        ? "bg-amber-500 animate-pulse"
        : "bg-rose-500";

  const statusText =
    connectionState === "connected"
      ? "Live"
      : connectionState === "reconnecting"
        ? "Reconnecting…"
        : connectionState === "auth_required"
          ? "Auth required"
          : "Offline";

  return (
    <div className="space-y-1.5 px-5 pb-4 pt-3 text-xs text-ink-500">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("h-2 w-2 rounded-full", statusDot)} />
          <span className="font-semibold uppercase tracking-widest text-[10px]">
            Daemon · {statusText}
          </span>
        </div>
        {onSignOut ? (
          <button
            type="button"
            onClick={onSignOut}
            title="Clear saved auth token"
            className="rounded-md p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-700"
          >
            <LogOut size={13} />
          </button>
        ) : null}
      </div>
      <div className="truncate text-[11px] text-ink-400">{serverUrl ?? ""}</div>
      {isLoading ? (
        <div className="text-[11px] text-ink-500">Syncing…</div>
      ) : null}
    </div>
  );
}

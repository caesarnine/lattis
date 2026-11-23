import React from "react";
import { Folder, FolderPlus, Globe, ChevronDown, ChevronUp } from "lucide-react";

import { type Workspace } from "@/services/lattisClient";
import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { cn } from "@/shared/utils";

type WorkspaceSwitcherProps = {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  onSelect: (workspaceId: string) => void;
  onRegister: (rootPath: string) => Promise<void>;
};

export function WorkspaceSwitcher({
  workspaces,
  activeWorkspaceId,
  onSelect,
  onRegister
}: WorkspaceSwitcherProps) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [newPath, setNewPath] = React.useState("");
  const [isAdding, setIsAdding] = React.useState(false);

  const active = workspaces.find((ws) => ws.id === activeWorkspaceId) ?? workspaces[0] ?? null;

  const handleAdd = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = newPath.trim();
    if (!trimmed || isAdding) return;
    setIsAdding(true);
    try {
      await onRegister(trimmed);
      setNewPath("");
      setIsOpen(false);
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="rounded-2xl border border-ink-200/70 bg-white/70 p-3">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full items-center justify-between gap-2 text-left"
      >
        <div className="flex min-w-0 items-center gap-2">
          {active?.kind === "global" ? (
            <Globe size={15} className="shrink-0 text-teal-600" />
          ) : (
            <Folder size={15} className="shrink-0 text-teal-600" />
          )}
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-ink-400">
              Workspace
            </div>
            <div className="truncate text-sm font-semibold text-ink-900">
              {active?.name ?? "Select workspace"}
            </div>
          </div>
        </div>
        {isOpen ? (
          <ChevronUp size={15} className="shrink-0 text-ink-500" />
        ) : (
          <ChevronDown size={15} className="shrink-0 text-ink-500" />
        )}
      </button>

      {isOpen ? (
        <div className="mt-3 space-y-2 border-t border-ink-200/60 pt-3">
          <div className="max-h-48 space-y-1 overflow-y-auto">
            {workspaces.map((ws) => {
              const isSelected = ws.id === activeWorkspaceId;
              return (
                <button
                  key={ws.id}
                  type="button"
                  onClick={() => {
                    onSelect(ws.id);
                    setIsOpen(false);
                  }}
                  className={cn(
                    "flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-2 text-left text-xs transition-colors",
                    isSelected
                      ? "bg-teal-100 text-teal-900 font-semibold"
                      : "text-ink-700 hover:bg-ink-100/80"
                  )}
                >
                  <div className="flex min-w-0 items-center gap-2">
                    {ws.kind === "global" ? (
                      <Globe size={13} className="shrink-0 opacity-75" />
                    ) : (
                      <Folder size={13} className="shrink-0 opacity-75" />
                    )}
                    <div className="min-w-0">
                      <div className="truncate">{ws.name}</div>
                      <div className="truncate text-[10px] font-normal text-ink-400">
                        {ws.root_path}
                      </div>
                    </div>
                  </div>
                  <span className="shrink-0 rounded-full bg-white/80 px-2 py-0.5 text-[10px] text-ink-500">
                    {ws.thread_count}
                  </span>
                </button>
              );
            })}
          </div>

          <form onSubmit={handleAdd} className="flex items-center gap-1.5 pt-1">
            <Input
              value={newPath}
              onChange={(event) => setNewPath(event.target.value)}
              placeholder="/path/to/project"
              className="h-8 text-xs"
            />
            <Button
              type="submit"
              size="icon"
              variant="outline"
              className="h-8 w-8 shrink-0"
              disabled={!newPath.trim() || isAdding}
              title="Register workspace folder"
            >
              <FolderPlus size={14} />
            </Button>
          </form>
        </div>
      ) : null}
    </div>
  );
}

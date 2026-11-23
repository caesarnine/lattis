import React from "react";
import {
  ArrowLeft,
  FileCode2,
  Folder,
  GitBranch,
  GitCompare,
  Link2,
  RefreshCcw,
  Wrench,
  X
} from "lucide-react";

import {
  getGitDiff,
  listWorkspaceFiles,
  readWorkspaceFile,
  type FileEntry,
  type GitDiff,
  type GitFileStatus,
  type GitStatus,
  type WorkspaceFileRead
} from "@/services/lattisClient";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { ScrollArea } from "@/shared/ui/scroll-area";
import { Separator } from "@/shared/ui/separator";
import { cn } from "@/shared/utils";

export type InspectorTab = "files" | "changes" | "toolkit";

type ToolkitEntry = {
  name: string;
  description?: string;
  path?: string;
  scope?: string;
  linked?: boolean;
};

type WorkspaceInspectorProps = {
  workspaceId: string | null;
  workspaceName: string;
  agentName: string;
  hasPluginState: boolean;
  pluginState: Record<string, unknown> | null;
  isLoadingPluginState: boolean;
  gitStatus: GitStatus | null;
  isLoadingGitStatus: boolean;
  activeTab: InspectorTab;
  onTabChange: (tab: InspectorTab) => void;
  onRefreshPluginState: () => void;
  onRefreshGitStatus: () => void;
  onClose: () => void;
};

function extractToolkitTools(state: Record<string, unknown> | null): ToolkitEntry[] | null {
  if (!state || !Array.isArray(state.tools)) return null;
  return state.tools.filter(
    (entry): entry is ToolkitEntry =>
      typeof entry === "object" &&
      entry !== null &&
      typeof (entry as { name?: unknown }).name === "string"
  );
}

function formatSize(bytes?: number | null): string {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusChip(status: GitFileStatus["status"]): { label: string; className: string } {
  switch (status) {
    case "added":
      return { label: "A", className: "bg-emerald-100 text-emerald-700" };
    case "deleted":
      return { label: "D", className: "bg-rose-100 text-rose-700" };
    case "untracked":
      return { label: "?", className: "bg-sky-100 text-sky-700" };
    case "renamed":
      return { label: "R", className: "bg-violet-100 text-violet-700" };
    case "conflicted":
      return { label: "!", className: "bg-amber-100 text-amber-800" };
    default:
      return { label: "M", className: "bg-amber-100 text-amber-800" };
  }
}

function UnifiedDiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <div className="text-xs text-ink-500">No diff output for this selection.</div>;
  }
  const lines = diff.split("\n");
  return (
    <pre className="overflow-x-auto rounded-2xl border border-ink-200/70 bg-white/85 p-3 font-mono text-[11px] leading-relaxed">
      {lines.map((line, index) => {
        const cls =
          line.startsWith("+++") || line.startsWith("---")
            ? "text-ink-500 font-semibold"
            : line.startsWith("@@")
              ? "bg-sky-50 text-sky-700"
              : line.startsWith("+")
                ? "bg-emerald-50 text-emerald-900"
                : line.startsWith("-")
                  ? "bg-rose-50 text-rose-900"
                  : "text-ink-700";
        return (
          <div key={index} className={cn("px-1.5 whitespace-pre", cls)}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

export function WorkspaceInspector({
  workspaceId,
  workspaceName,
  agentName,
  hasPluginState,
  pluginState,
  isLoadingPluginState,
  gitStatus,
  isLoadingGitStatus,
  activeTab,
  onTabChange,
  onRefreshPluginState,
  onRefreshGitStatus,
  onClose
}: WorkspaceInspectorProps) {
  // Files browser state
  const [currentDir, setCurrentDir] = React.useState("");
  const [entries, setEntries] = React.useState<FileEntry[]>([]);
  const [isLoadingFiles, setIsLoadingFiles] = React.useState(false);
  const [selectedFile, setSelectedFile] = React.useState<WorkspaceFileRead | null>(null);
  const [fileError, setFileError] = React.useState<string | null>(null);

  // Changes / Diff viewer state
  const [selectedDiffFile, setSelectedDiffFile] = React.useState<GitFileStatus | null>(null);
  const [diffData, setDiffData] = React.useState<GitDiff | null>(null);
  const [isLoadingDiff, setIsLoadingDiff] = React.useState(false);

  // Reset file/diff selection when workspace switches
  React.useEffect(() => {
    setCurrentDir("");
    setEntries([]);
    setSelectedFile(null);
    setSelectedDiffFile(null);
    setDiffData(null);
    setFileError(null);
  }, [workspaceId]);

  // If toolkit tab becomes unavailable, switch to files
  React.useEffect(() => {
    if (activeTab === "toolkit" && !hasPluginState) {
      onTabChange("files");
    }
  }, [activeTab, hasPluginState, onTabChange]);

  const loadDirectory = React.useCallback(
    async (dirPath: string) => {
      if (!workspaceId) return;
      setIsLoadingFiles(true);
      setFileError(null);
      try {
        const res = await listWorkspaceFiles(workspaceId, { path: dirPath });
        setCurrentDir(res.path);
        setEntries(res.entries);
      } catch (err) {
        setFileError(err instanceof Error ? err.message : "Failed to load directory");
      } finally {
        setIsLoadingFiles(false);
      }
    },
    [workspaceId]
  );

  React.useEffect(() => {
    if (activeTab === "files" && workspaceId) {
      void loadDirectory(currentDir);
    }
  }, [activeTab, currentDir, loadDirectory, workspaceId]);

  const handleOpenEntry = async (entry: FileEntry) => {
    if (!workspaceId) return;
    if (entry.kind === "dir") {
      setSelectedFile(null);
      setCurrentDir(entry.path);
      return;
    }
    setIsLoadingFiles(true);
    setFileError(null);
    try {
      const read = await readWorkspaceFile(workspaceId, entry.path);
      setSelectedFile(read);
    } catch (err) {
      setFileError(err instanceof Error ? err.message : "Failed to read file");
    } finally {
      setIsLoadingFiles(false);
    }
  };

  const handleSelectGitFile = async (file: GitFileStatus) => {
    if (!workspaceId) return;
    setSelectedDiffFile(file);
    setIsLoadingDiff(true);
    try {
      const isStagedOnly =
        file.index_status !== " " &&
        file.index_status !== "?" &&
        file.worktree_status === " ";
      const res = await getGitDiff(workspaceId, {
        path: file.path,
        staged: isStagedOnly
      });
      setDiffData(res);
    } catch {
      setDiffData(null);
    } finally {
      setIsLoadingDiff(false);
    }
  };

  const handleRefresh = () => {
    if (activeTab === "files") {
      void loadDirectory(currentDir);
    } else if (activeTab === "changes") {
      onRefreshGitStatus();
      if (selectedDiffFile) {
        void handleSelectGitFile(selectedDiffFile);
      }
    } else {
      onRefreshPluginState();
    }
  };

  const parentDir = currentDir.includes("/")
    ? currentDir.slice(0, currentDir.lastIndexOf("/"))
    : "";

  const tools = extractToolkitTools(pluginState);
  const toolkitDir = typeof pluginState?.toolkit_dir === "string" ? pluginState.toolkit_dir : null;
  const linkDir = typeof pluginState?.link_dir === "string" ? pluginState.link_dir : null;
  const changedCount = gitStatus?.files?.length ?? 0;

  return (
    <aside className="flex h-full w-full md:w-96 flex-col border-ink-200/70 bg-glass shadow-soft md:rounded-3xl md:border overflow-hidden">
      <div className="space-y-3 px-4 pb-3 pt-4">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.25em] text-ink-500 truncate">
              {workspaceName || "Workspace"}
            </div>
            <div className="text-lg font-display text-ink-900">Inspector</div>
          </div>
          <div className="flex items-center gap-1">
            <Button
              size="icon"
              variant="ghost"
              onClick={handleRefresh}
              disabled={isLoadingFiles || isLoadingGitStatus || isLoadingPluginState}
            >
              <RefreshCcw size={15} />
            </Button>
            <Button size="icon" variant="ghost" onClick={onClose}>
              <X size={15} />
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-1 rounded-2xl border border-ink-200/70 bg-white/60 p-1">
          <button
            type="button"
            onClick={() => onTabChange("files")}
            className={cn(
              "flex items-center justify-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-semibold transition-colors",
              activeTab === "files"
                ? "bg-ink-900 text-white shadow-sm"
                : "text-ink-600 hover:bg-white/80"
            )}
          >
            <Folder size={13} />
            Files
          </button>
          <button
            type="button"
            onClick={() => onTabChange("changes")}
            className={cn(
              "flex items-center justify-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-semibold transition-colors",
              activeTab === "changes"
                ? "bg-ink-900 text-white shadow-sm"
                : "text-ink-600 hover:bg-white/80"
            )}
          >
            <GitCompare size={13} />
            Changes
            {changedCount > 0 ? (
              <span
                className={cn(
                  "rounded-full px-1.5 py-0.2 text-[10px]",
                  activeTab === "changes"
                    ? "bg-white/20 text-white"
                    : "bg-teal-100 text-teal-800"
                )}
              >
                {changedCount}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            disabled={!hasPluginState}
            onClick={() => onTabChange("toolkit")}
            className={cn(
              "flex items-center justify-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-semibold transition-colors",
              !hasPluginState
                ? "opacity-40 cursor-not-allowed text-ink-400"
                : activeTab === "toolkit"
                  ? "bg-ink-900 text-white shadow-sm"
                  : "text-ink-600 hover:bg-white/80"
            )}
          >
            <Wrench size={13} />
            Toolkit
          </button>
        </div>
      </div>

      <Separator />

      <ScrollArea className="flex-1 px-4 py-3">
        {/* FILES TAB */}
        {activeTab === "files" ? (
          selectedFile ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedFile(null)}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-teal-700 hover:text-teal-900"
                >
                  <ArrowLeft size={14} />
                  Back
                </button>
                <span className="truncate font-mono text-[11px] text-ink-500">
                  {selectedFile.path}
                </span>
              </div>
              {selectedFile.is_binary ? (
                <div className="rounded-2xl border border-dashed border-ink-200 bg-white/60 p-4 text-xs text-ink-500">
                  Binary file ({formatSize(selectedFile.size)})
                </div>
              ) : (
                <pre className="overflow-x-auto rounded-2xl border border-ink-200/70 bg-white/85 p-3 font-mono text-[11px] leading-relaxed text-ink-900">
                  {selectedFile.content || "(empty file)"}
                </pre>
              )}
              {selectedFile.truncated ? (
                <div className="text-[11px] text-amber-700">
                  File truncated at 256 KB preview limit.
                </div>
              ) : null}
            </div>
          ) : (
            <div className="space-y-2">
              {currentDir ? (
                <button
                  type="button"
                  onClick={() => setCurrentDir(parentDir)}
                  className="flex w-full items-center gap-2 rounded-xl px-2.5 py-1.5 text-xs font-semibold text-teal-700 hover:bg-white/70"
                >
                  <ArrowLeft size={13} />
                  <span className="truncate font-mono">{currentDir}</span>
                </button>
              ) : null}
              {fileError ? (
                <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">
                  {fileError}
                </div>
              ) : null}
              {isLoadingFiles && entries.length === 0 ? (
                <div className="text-xs text-ink-500">Loading files…</div>
              ) : entries.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-ink-200 bg-white/50 p-4 text-xs text-ink-500">
                  Directory is empty.
                </div>
              ) : (
                <div className="space-y-1">
                  {entries.map((entry) => (
                    <button
                      key={entry.path}
                      type="button"
                      onClick={() => void handleOpenEntry(entry)}
                      className="flex w-full items-center justify-between gap-2 rounded-xl px-2.5 py-2 text-left text-xs text-ink-700 hover:bg-white/80"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        {entry.kind === "dir" ? (
                          <Folder size={14} className="shrink-0 text-teal-600" />
                        ) : (
                          <FileCode2 size={14} className="shrink-0 text-ink-400" />
                        )}
                        <span className="truncate font-mono">{entry.name}</span>
                      </div>
                      {entry.kind === "file" ? (
                        <span className="shrink-0 text-[10px] text-ink-400">
                          {formatSize(entry.size)}
                        </span>
                      ) : null}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )
        ) : null}

        {/* CHANGES / GIT TAB */}
        {activeTab === "changes" ? (
          !gitStatus?.is_git_repo ? (
            <div className="rounded-2xl border border-dashed border-ink-200 bg-white/50 p-4 text-xs text-ink-500">
              This workspace is not a Git repository.
            </div>
          ) : selectedDiffFile ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedDiffFile(null);
                    setDiffData(null);
                  }}
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-teal-700 hover:text-teal-900"
                >
                  <ArrowLeft size={14} />
                  All Changes
                </button>
                <span className="truncate font-mono text-[11px] text-ink-600">
                  {selectedDiffFile.path}
                </span>
              </div>
              {isLoadingDiff ? (
                <div className="text-xs text-ink-500">Loading diff…</div>
              ) : (
                <UnifiedDiffView diff={diffData?.diff ?? ""} />
              )}
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded-2xl border border-ink-200/70 bg-white/70 px-3 py-2 text-xs">
                <div className="flex items-center gap-1.5 font-semibold text-ink-800">
                  <GitBranch size={13} className="text-teal-600" />
                  <span>{gitStatus.branch ?? "HEAD"}</span>
                </div>
                {(gitStatus.ahead ?? 0) > 0 || (gitStatus.behind ?? 0) > 0 ? (
                  <span className="font-mono text-[10px] text-ink-500">
                    ↑{gitStatus.ahead ?? 0} ↓{gitStatus.behind ?? 0}
                  </span>
                ) : null}
              </div>

              {(gitStatus.files ?? []).length === 0 ? (
                <div className="rounded-2xl border border-dashed border-ink-200 bg-white/50 p-4 text-xs text-ink-500">
                  Working tree clean.
                </div>
              ) : (
                <div className="space-y-1">
                  {(gitStatus.files ?? []).map((file) => {
                    const chip = statusChip(file.status);
                    return (
                      <button
                        key={file.path}
                        type="button"
                        onClick={() => void handleSelectGitFile(file)}
                        className="flex w-full items-center justify-between gap-2 rounded-xl border border-transparent bg-white/60 px-2.5 py-2 text-left text-xs hover:border-ink-200 hover:bg-white"
                      >
                        <span className="truncate font-mono text-ink-800">{file.path}</span>
                        <span
                          className={cn(
                            "shrink-0 rounded-md px-1.5 py-0.5 font-mono text-[10px] font-bold",
                            chip.className
                          )}
                        >
                          {chip.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )
        ) : null}

        {/* TOOLKIT / PLUGIN STATE TAB */}
        {activeTab === "toolkit" ? (
          isLoadingPluginState && !pluginState ? (
            <div className="text-xs text-ink-500">Loading {agentName} state…</div>
          ) : tools ? (
            <div className="space-y-2.5">
              {tools.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-ink-200 bg-white/50 p-4 text-xs text-ink-500">
                  No forged tools yet. Ask Binsmith to automate a repeated task and your
                  scripts will appear here live.
                </div>
              ) : (
                tools.map((tool) => (
                  <div
                    key={`${tool.scope ?? "global"}-${tool.name}`}
                    className="rounded-2xl border border-ink-200/70 bg-white/70 p-3 shadow-sm"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-xs font-semibold text-ink-900">
                        {tool.name}
                      </span>
                      <div className="flex shrink-0 items-center gap-1">
                        {tool.scope === "project" ? (
                          <Badge variant="accent" className="text-[9px] uppercase">
                            project
                          </Badge>
                        ) : null}
                        {tool.linked ? (
                          <span
                            title={linkDir ? `Linked in ${linkDir}` : "Linked on PATH"}
                            className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700"
                          >
                            <Link2 size={10} />
                            PATH
                          </span>
                        ) : null}
                      </div>
                    </div>
                    {tool.description ? (
                      <p className="mt-1 text-xs leading-relaxed text-ink-600">
                        {tool.description}
                      </p>
                    ) : null}
                  </div>
                ))
              )}
            </div>
          ) : pluginState ? (
            <pre className="whitespace-pre-wrap break-all rounded-2xl border border-ink-200/60 bg-white/70 p-3 font-mono text-[11px] text-ink-800">
              {JSON.stringify(pluginState, null, 2)}
            </pre>
          ) : (
            <div className="text-xs text-ink-500">No state reported by this agent.</div>
          )
        ) : null}
      </ScrollArea>

      {activeTab === "toolkit" && toolkitDir ? (
        <>
          <Separator />
          <div className="space-y-1 px-4 py-2.5 text-[10px] text-ink-400">
            <div className="truncate" title={toolkitDir}>
              bin: {toolkitDir}/bin
            </div>
            {linkDir ? (
              <div className="truncate" title={linkDir}>
                linked: {linkDir}
              </div>
            ) : null}
          </div>
        </>
      ) : null}
    </aside>
  );
}

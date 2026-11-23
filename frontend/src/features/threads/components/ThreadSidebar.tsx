import { Plus, RefreshCcw, X } from "lucide-react";

import { AgentSelector } from "@/features/threads/components/AgentSelector";
import { ModelSelector } from "@/features/threads/components/ModelSelector";
import { ThreadList } from "@/features/threads/components/ThreadList";
import { ThreadSidebarFooter } from "@/features/threads/components/ThreadSidebarFooter";
import { WorkspaceSwitcher } from "@/features/threads/components/WorkspaceSwitcher";
import { type AgentInfo, type Thread, type Workspace } from "@/services/lattisClient";
import { Button } from "@/shared/ui/button";
import { ScrollArea } from "@/shared/ui/scroll-area";
import { Separator } from "@/shared/ui/separator";

type WorkspaceSection = {
  list: Workspace[];
  activeId: string | null;
  onSelect: (workspaceId: string) => void;
  onRegister: (rootPath: string) => Promise<void>;
};

type ThreadSection = {
  list: Thread[];
  currentId: string | null;
  isLoading?: boolean;
  onSelect: (threadId: string) => void;
  onCreate: () => void;
  onClear: (threadId: string) => void;
  onDelete: (threadId: string) => void;
  onRefresh: () => void;
};

type AgentSection = {
  selectedId: string | null;
  selectedName: string | null;
  defaultId: string | null;
  list: AgentInfo[] | null;
  isLoading?: boolean;
  onLoad?: () => void;
  onSelect?: (agent: string | null) => void;
};

type ModelSection = {
  selectedId: string | null;
  defaultId: string | null;
  list: string[] | null;
  isLoading?: boolean;
  onLoad?: () => void;
  onSelect?: (model: string | null) => void;
};

type DaemonSummary = {
  serverUrl?: string;
  connectionState: "connected" | "reconnecting" | "auth_required" | "error";
  onSignOut?: () => void;
};

export type ThreadSidebarProps = {
  workspaces: WorkspaceSection;
  threads: ThreadSection;
  agents: AgentSection;
  models: ModelSection;
  daemon: DaemonSummary;
  onClose?: () => void;
};

export function ThreadSidebar({
  workspaces,
  threads,
  agents,
  models,
  daemon,
  onClose
}: ThreadSidebarProps) {
  const hasWorkspace = Boolean(workspaces.activeId);

  return (
    <aside className="flex h-full flex-col border-ink-200/70 bg-glass shadow-soft md:rounded-3xl md:border overflow-hidden">
      <div className="space-y-3 px-5 pb-4 pt-5">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.3em] text-ink-500">
              Lattis
            </div>
            <div className="text-2xl font-display text-ink-900">Workspace</div>
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              size="icon"
              variant="ghost"
              onClick={threads.onRefresh}
              disabled={!hasWorkspace || threads.isLoading}
            >
              <RefreshCcw size={16} />
            </Button>
            {onClose ? (
              <Button size="icon" variant="ghost" onClick={onClose}>
                <X size={16} />
              </Button>
            ) : null}
          </div>
        </div>

        <WorkspaceSwitcher
          workspaces={workspaces.list}
          activeWorkspaceId={workspaces.activeId}
          onSelect={workspaces.onSelect}
          onRegister={workspaces.onRegister}
        />

        <Button
          className="w-full rounded-2xl bg-ink-900 py-5 text-white hover:bg-ink-800"
          onClick={threads.onCreate}
          disabled={!hasWorkspace}
        >
          <Plus size={16} className="mr-2" />
          New Thread
        </Button>

        <AgentSelector
          agentId={agents.selectedId}
          agentName={agents.selectedName}
          defaultAgent={agents.defaultId}
          agents={agents.list}
          isLoading={agents.isLoading}
          onLoad={agents.onLoad}
          onSelect={agents.onSelect}
        />

        <ModelSelector
          modelId={models.selectedId}
          defaultModel={models.defaultId}
          models={models.list}
          isLoading={models.isLoading}
          onLoad={models.onLoad}
          onSelect={models.onSelect}
        />
      </div>

      <Separator />

      <ScrollArea className="flex-1 px-3 py-3">
        <ThreadList
          threads={threads.list}
          currentThreadId={threads.currentId}
          onSelect={threads.onSelect}
          onClear={threads.onClear}
          onDelete={threads.onDelete}
        />
      </ScrollArea>

      <Separator />

      <ThreadSidebarFooter
        serverUrl={daemon.serverUrl}
        connectionState={daemon.connectionState}
        isLoading={threads.isLoading}
        onSignOut={daemon.onSignOut}
      />
    </aside>
  );
}

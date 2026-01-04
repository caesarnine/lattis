import { Plus, RefreshCcw, X } from "lucide-react";

import { AgentSelector } from "@/features/threads/components/AgentSelector";
import { ModelSelector } from "@/features/threads/components/ModelSelector";
import { ThreadList } from "@/features/threads/components/ThreadList";
import { ThreadSidebarFooter } from "@/features/threads/components/ThreadSidebarFooter";
import { Button } from "@/shared/ui/button";
import { ScrollArea } from "@/shared/ui/scroll-area";
import { Separator } from "@/shared/ui/separator";
import { type AgentInfo } from "@/services/latticeApi";

type ThreadSection = {
  list: string[];
  current: string | null;
  isLoading?: boolean;
  onSelect: (threadId: string) => void;
  onCreate: () => void;
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

type SessionSummary = {
  id?: string | null;
  serverUrl?: string;
};

export type ThreadSidebarProps = {
  threads: ThreadSection;
  agents: AgentSection;
  models: ModelSection;
  session: SessionSummary;
  onClose?: () => void;
};

export function ThreadSidebar({
  threads,
  agents,
  models,
  session,
  onClose
}: ThreadSidebarProps) {
  const hasSession = Boolean(session.id);

  return (
    <aside className="flex h-full flex-col border-ink-200/70 bg-glass shadow-soft md:rounded-3xl md:border overflow-hidden">
      <div className="space-y-4 px-5 pb-4 pt-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.3em] text-ink-500">
              Lattice
            </div>
            <div className="text-2xl font-display text-ink-900">Threads</div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="icon"
              variant="ghost"
              onClick={threads.onRefresh}
              disabled={!hasSession || threads.isLoading}
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
        <Button
          className="w-full rounded-2xl bg-ink-900 py-6 text-white hover:bg-ink-800"
          onClick={threads.onCreate}
          disabled={!hasSession}
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

      <ScrollArea className="flex-1 px-3 py-4">
        <ThreadList
          threads={threads.list}
          currentThread={threads.current}
          onSelect={threads.onSelect}
        />
      </ScrollArea>

      <Separator />

      <ThreadSidebarFooter
        sessionId={session.id}
        serverUrl={session.serverUrl}
        isLoading={threads.isLoading}
      />
    </aside>
  );
}

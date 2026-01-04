import React from "react";

import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { ScrollArea } from "@/shared/ui/scroll-area";
import { cn } from "@/shared/utils";
import { type AgentInfo } from "@/services/latticeApi";

type AgentSelectorProps = {
  agentId: string | null;
  agentName: string | null;
  defaultAgent: string | null;
  agents: AgentInfo[] | null;
  isLoading?: boolean;
  onLoad?: () => void;
  onSelect?: (agent: string | null) => void;
};

export function AgentSelector({
  agentId,
  agentName,
  defaultAgent,
  agents,
  isLoading,
  onLoad,
  onSelect
}: AgentSelectorProps) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    if (isOpen && onLoad) {
      onLoad();
    }
  }, [isOpen, onLoad]);

  const displayAgent = agentName || agentId || defaultAgent || "Default";
  const normalizedQuery = query.trim().toLowerCase();
  const allAgents = agents ?? [];
  const filteredAgents = normalizedQuery
    ? allAgents.filter((item) => {
        const name = item.name ?? "";
        return (
          name.toLowerCase().includes(normalizedQuery) ||
          item.id.toLowerCase().includes(normalizedQuery)
        );
      })
    : allAgents;
  const visibleAgents = normalizedQuery
    ? filteredAgents
    : filteredAgents.slice(0, 50);

  return (
    <div className="rounded-2xl border border-ink-200/70 bg-white/60 p-3">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full items-center justify-between text-left text-xs font-semibold uppercase tracking-widest text-ink-500"
      >
        <span>Agent</span>
        <span
          className="max-w-[140px] truncate text-ink-900 normal-case"
          title={displayAgent}
        >
          {displayAgent}
        </span>
      </button>
      {isOpen ? (
        <div className="mt-3 space-y-3">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search agents"
            className="h-9 text-xs"
          />
          <div className="max-h-56 overflow-hidden rounded-xl border border-ink-200/60 bg-white/70">
            <ScrollArea className="h-56 px-2 py-2">
              {isLoading ? (
                <div className="p-2 text-xs text-ink-500">Loading agents...</div>
              ) : visibleAgents.length ? (
                visibleAgents.map((item) => {
                  const isSelected = item.id === agentId;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        onSelect?.(item.id);
                        setIsOpen(false);
                        setQuery("");
                      }}
                      className={cn(
                        "w-full rounded-lg px-3 py-2 text-left text-xs transition-colors",
                        isSelected
                          ? "bg-teal-100 text-teal-900"
                          : "text-ink-600 hover:bg-ink-100/70"
                      )}
                    >
                      <div className="font-semibold">{item.name || item.id}</div>
                      <div className="mt-0.5 truncate text-[10px] text-ink-400">
                        {item.id}
                      </div>
                    </button>
                  );
                })
              ) : (
                <div className="p-2 text-xs text-ink-500">No matches.</div>
              )}
            </ScrollArea>
          </div>
          {!normalizedQuery && allAgents.length > visibleAgents.length ? (
            <div className="text-[11px] text-ink-400">
              Showing {visibleAgents.length} of {allAgents.length}. Type to search.
            </div>
          ) : null}
          {defaultAgent && agentId && agentId !== defaultAgent ? (
            <Button
              size="sm"
              variant="outline"
              className="w-full text-xs"
              onClick={() => {
                onSelect?.(null);
                setIsOpen(false);
                setQuery("");
              }}
            >
              Reset to default
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

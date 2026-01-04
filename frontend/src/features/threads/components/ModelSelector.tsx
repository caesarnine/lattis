import React from "react";

import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";
import { ScrollArea } from "@/shared/ui/scroll-area";
import { cn } from "@/shared/utils";

type ModelSelectorProps = {
  modelId: string | null;
  defaultModel: string | null;
  models: string[] | null;
  isLoading?: boolean;
  onLoad?: () => void;
  onSelect?: (model: string | null) => void;
};

export function ModelSelector({
  modelId,
  defaultModel,
  models,
  isLoading,
  onLoad,
  onSelect
}: ModelSelectorProps) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    if (isOpen && onLoad) {
      onLoad();
    }
  }, [isOpen, onLoad]);

  const displayModel = modelId || defaultModel || "Default";
  const normalizedQuery = query.trim().toLowerCase();
  const allModels = models ?? [];
  const filteredModels = normalizedQuery
    ? allModels.filter((item) => item.toLowerCase().includes(normalizedQuery))
    : allModels;
  const visibleModels = normalizedQuery
    ? filteredModels
    : filteredModels.slice(0, 50);

  return (
    <div className="rounded-2xl border border-ink-200/70 bg-white/60 p-3">
      <button
        type="button"
        onClick={() => setIsOpen((open) => !open)}
        className="flex w-full items-center justify-between text-left text-xs font-semibold uppercase tracking-widest text-ink-500"
      >
        <span>Model</span>
        <span
          className="max-w-[140px] truncate text-ink-900 normal-case"
          title={displayModel}
        >
          {displayModel}
        </span>
      </button>
      {isOpen ? (
        <div className="mt-3 space-y-3">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search models"
            className="h-9 text-xs"
          />
          <div className="max-h-56 overflow-hidden rounded-xl border border-ink-200/60 bg-white/70">
            <ScrollArea className="h-56 px-2 py-2">
              {isLoading ? (
                <div className="p-2 text-xs text-ink-500">Loading models...</div>
              ) : visibleModels.length ? (
                visibleModels.map((item) => (
                  <button
                    key={item}
                    type="button"
                    onClick={() => {
                      onSelect?.(item);
                      setIsOpen(false);
                      setQuery("");
                    }}
                    className={cn(
                      "w-full rounded-lg px-3 py-2 text-left text-xs transition-colors",
                      item === displayModel
                        ? "bg-teal-100 text-teal-900"
                        : "text-ink-600 hover:bg-ink-100/70"
                    )}
                  >
                    {item}
                  </button>
                ))
              ) : (
                <div className="p-2 text-xs text-ink-500">No matches.</div>
              )}
            </ScrollArea>
          </div>
          {!normalizedQuery && allModels.length > visibleModels.length ? (
            <div className="text-[11px] text-ink-400">
              Showing {visibleModels.length} of {allModels.length}. Type to search.
            </div>
          ) : null}
          {defaultModel && displayModel !== defaultModel ? (
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

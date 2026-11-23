import React from "react";

import { appendToolArgs, parseToolResult } from "@/features/chat/format";
import {
  type ApprovalItem,
  type ChatRole,
  type MessageItem,
  type RenderItem,
  type ToolItem
} from "@/features/chat/types";
import { type Item, type LattisEvent } from "@/services/lattisClient";
import { createId } from "@/shared/ids";

function stringifyArgs(payload: Record<string, unknown>): string {
  const argsRaw = payload.args_raw;
  if (typeof argsRaw === "string" && argsRaw.trim()) {
    return argsRaw;
  }
  const args = payload.args;
  if (typeof args === "string") return args;
  if (args && typeof args === "object") {
    try {
      return JSON.stringify(args);
    } catch {
      return String(args);
    }
  }
  return "";
}

function itemToRenderItem(item: Item): RenderItem | null {
  const payload = (item.payload ?? {}) as Record<string, unknown>;

  if (item.kind === "user_message") {
    return {
      kind: "message",
      id: item.id,
      role: "user",
      content: typeof payload.text === "string" ? payload.text : "",
      status: item.status
    };
  }

  if (item.kind === "assistant_text") {
    return {
      kind: "message",
      id: item.id,
      role: "assistant",
      content: typeof payload.text === "string" ? payload.text : "",
      status: item.status
    };
  }

  if (item.kind === "reasoning") {
    return {
      kind: "message",
      id: item.id,
      role: "thinking",
      content: typeof payload.text === "string" ? payload.text : "",
      status: item.status
    };
  }

  if (item.kind === "system_note") {
    return {
      kind: "message",
      id: item.id,
      role: "system",
      content: typeof payload.text === "string" ? payload.text : "",
      status: item.status
    };
  }

  if (item.kind === "approval_request") {
    const decision =
      payload.decision === "approved" || payload.decision === "denied"
        ? payload.decision
        : null;
    const approval: ApprovalItem = {
      kind: "approval",
      id: item.id,
      runId: item.run_id ?? "",
      approvalId: typeof payload.approval_id === "string" ? payload.approval_id : item.id,
      toolName: typeof payload.tool_name === "string" ? payload.tool_name : "tool",
      args: payload.args ?? {},
      decision,
      reason: typeof payload.reason === "string" ? payload.reason : null
    };
    return approval;
  }

  if (item.kind === "tool_call") {
    const outputStream = typeof payload.output_stream === "string" ? payload.output_stream : "";
    const hasResult = payload.result !== undefined && payload.result !== null;
    let result = hasResult ? parseToolResult(payload.result) : undefined;
    if (!result && item.status !== "streaming") {
      result = {
        output: outputStream,
        exitCode: payload.is_error || item.status === "error" ? 1 : 0,
        timedOut: false
      };
    }
    const tool: ToolItem = {
      kind: "tool",
      id: item.id,
      toolName: typeof payload.tool_name === "string" ? payload.tool_name : "tool",
      argsRaw: stringifyArgs(payload),
      outputStream,
      status: item.status,
      result
    };
    return tool;
  }

  return null;
}

export function useChatItems() {
  const [items, setItems] = React.useState<RenderItem[]>([]);

  const clearItems = React.useCallback(() => {
    setItems([]);
  }, []);

  const addSystemMessage = React.useCallback((content: string, id?: string) => {
    const message: MessageItem = {
      kind: "message",
      id: id ?? createId("system"),
      role: "system",
      content
    };
    setItems((prev) => [...prev, message]);
  }, []);

  const upsertItem = React.useCallback((item: Item) => {
    const mapped = itemToRenderItem(item);
    if (!mapped) return;
    setItems((prev) => {
      const idx = prev.findIndex((existing) => existing.id === mapped.id);
      if (idx === -1) {
        return [...prev, mapped];
      }
      const next = [...prev];
      // Preserve accumulated live output stream if server completed without echoing it
      const existing = prev[idx];
      if (
        existing.kind === "tool" &&
        mapped.kind === "tool" &&
        !mapped.outputStream &&
        existing.outputStream
      ) {
        next[idx] = { ...mapped, outputStream: existing.outputStream };
      } else {
        next[idx] = mapped;
      }
      return next;
    });
  }, []);

  const hydrateItems = React.useCallback((serverItems: Item[]) => {
    const mapped: RenderItem[] = [];
    for (const item of serverItems) {
      const render = itemToRenderItem(item);
      if (render) {
        mapped.push(render);
      }
    }
    setItems(mapped);
  }, []);

  const applyDelta = React.useCallback(
    (itemId: string, channel: "text" | "reasoning" | "tool_input" | "tool_output", delta: string) => {
      if (!delta) return;
      setItems((prev) => {
        const idx = prev.findIndex((entry) => entry.id === itemId);
        if (idx === -1) {
          if (channel === "text" || channel === "reasoning") {
            const role: ChatRole = channel === "reasoning" ? "thinking" : "assistant";
            return [
              ...prev,
              {
                kind: "message",
                id: itemId,
                role,
                content: delta,
                status: "streaming"
              }
            ];
          }
          return prev;
        }

        const next = [...prev];
        const target = next[idx];
        if ((channel === "text" || channel === "reasoning") && target.kind === "message") {
          next[idx] = { ...target, content: target.content + delta };
          return next;
        }
        if (channel === "tool_input" && target.kind === "tool") {
          next[idx] = { ...target, argsRaw: appendToolArgs(target.argsRaw, delta) };
          return next;
        }
        if (channel === "tool_output" && target.kind === "tool") {
          next[idx] = { ...target, outputStream: target.outputStream + delta };
          return next;
        }
        return prev;
      });
    },
    []
  );

  const handleThreadEvent = React.useCallback(
    (event: LattisEvent) => {
      switch (event.type) {
        case "item.created":
        case "item.completed":
          upsertItem(event.data);
          return;
        case "item.delta":
          applyDelta(event.data.item_id, event.data.channel, event.data.delta);
          return;
        case "thread.cleared":
          clearItems();
          return;
        case "run.failed":
          addSystemMessage(`Run failed: ${event.data.error ?? "Unknown error"}`);
          return;
        case "run.cancelled":
          addSystemMessage("Run cancelled.");
          return;
        default:
          return;
      }
    },
    [addSystemMessage, applyDelta, clearItems, upsertItem]
  );

  return {
    items,
    clearItems,
    addSystemMessage,
    upsertItem,
    hydrateItems,
    handleThreadEvent
  };
}

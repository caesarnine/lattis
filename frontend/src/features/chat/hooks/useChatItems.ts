import React from "react";

import { appendToolArgs, parseToolResult } from "@/features/chat/format";
import { type ChatRole, type MessageItem, type RenderItem, type ToolItem } from "@/features/chat/types";
import { createId } from "@/shared/ids";
import { type UiMessage, type UiMessagePart, type UiStreamEvent } from "@/services/vercel";

const EMPTY_MESSAGE = "";

type UiToolPart = Extract<
  UiMessagePart,
  { toolCallId: string; state: string; type: string }
>;

type AddMessageInput = {
  id?: string;
  role: ChatRole;
  content: string;
};

function isUiToolPart(part: UiMessagePart): part is UiToolPart {
  return (
    typeof (part as { toolCallId?: unknown }).toolCallId === "string" &&
    typeof (part as { state?: unknown }).state === "string"
  );
}

function stringifyToolInput(input: unknown): string {
  if (typeof input === "string") return input;
  if (input == null) return "";
  try {
    return JSON.stringify(input);
  } catch {
    return String(input);
  }
}

function describeFilePart(part: UiMessagePart): string | null {
  if (part.type !== "file") return null;
  const filePart = part as Extract<UiMessagePart, { type: "file" }>;
  const label = filePart.filename ?? filePart.mediaType ?? "file";
  return `[${label}]`;
}

function extractToolName(part: UiToolPart): string {
  if (part.type === "dynamic-tool") {
    return (part as { toolName?: unknown }).toolName?.toString() ?? "tool";
  }
  if (part.type.startsWith("tool-")) {
    return part.type.slice("tool-".length) || "tool";
  }
  return "tool";
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

export function useChatItems() {
  const [items, setItems] = React.useState<RenderItem[]>([]);

  const clearItems = React.useCallback(() => {
    setItems([]);
  }, []);

  const addMessageItem = React.useCallback((message: MessageItem) => {
    setItems((prev) => [...prev, message]);
  }, []);

  const addMessage = React.useCallback(
    ({ id, role, content }: AddMessageInput) => {
      const messageId = id ?? createId(role);
      addMessageItem({
        kind: "message",
        id: messageId,
        role,
        content
      });
    },
    [addMessageItem]
  );

  const ensureMessageItem = React.useCallback(
    (message: MessageItem) => {
      setItems((prev) => {
        const index = prev.findIndex(
          (item) => item.kind === "message" && item.id === message.id
        );
        if (index !== -1) {
          return prev;
        }
        return [...prev, message];
      });
    },
    []
  );

  const addSystemMessage = React.useCallback(
    (content: string, id?: string) => {
      addMessage({
        id: id ?? createId("system"),
        role: "system",
        content
      });
    },
    [addMessage]
  );

  const updateMessageContent = React.useCallback(
    (messageId: string, delta: string, fallbackRole: ChatRole = "assistant") => {
      if (!delta) return;

      setItems((prev) => {
        const index = prev.findIndex(
          (item) => item.kind === "message" && item.id === messageId
        );
        if (index === -1) {
          const fallbackMessage: MessageItem = {
            kind: "message",
            id: messageId,
            role: fallbackRole,
            content: delta
          };
          return [...prev, fallbackMessage];
        }

        const next = [...prev];
        const item = next[index];
        if (item.kind !== "message") return prev;
        next[index] = {
          ...item,
          content: item.content + delta
        };
        return next;
      });
    },
    []
  );

  const updateToolItem = React.useCallback(
    (toolId: string, updater: (item: ToolItem) => ToolItem) => {
      setItems((prev) => {
        const index = prev.findIndex(
          (item) => item.kind === "tool" && item.id === toolId
        );
        if (index === -1) return prev;
        const next = [...prev];
        const item = next[index];
        if (item.kind !== "tool") return prev;
        next[index] = updater(item);
        return next;
      });
    },
    []
  );

  const ensureToolItem = React.useCallback(
    (toolCallId: string, toolName?: string) => {
      if (!toolCallId) return;
      setItems((prev) => {
        const index = prev.findIndex(
          (item) => item.kind === "tool" && item.id === toolCallId
        );
        if (index !== -1) {
          if (toolName) {
            const item = prev[index];
            if (item.kind === "tool" && item.toolName === "tool") {
              const next = [...prev];
              next[index] = { ...item, toolName };
              return next;
            }
          }
          return prev;
        }
        return [
          ...prev,
          {
            kind: "tool",
            id: toolCallId,
            toolName: toolName ?? "tool",
            argsRaw: ""
          }
        ];
      });
    },
    []
  );

  const setToolArgs = React.useCallback(
    (toolCallId: string, input: unknown) => {
      if (!toolCallId) return;
      ensureToolItem(toolCallId);
      updateToolItem(toolCallId, (item) => ({
        ...item,
        argsRaw: stringifyToolInput(input)
      }));
    },
    [ensureToolItem, updateToolItem]
  );

  const setToolResult = React.useCallback(
    (toolCallId: string, output: unknown) => {
      if (!toolCallId) return;
      ensureToolItem(toolCallId);
      updateToolItem(toolCallId, (item) => ({
        ...item,
        result: parseToolResult(output)
      }));
    },
    [ensureToolItem, updateToolItem]
  );

  const handleStreamEvent = React.useCallback(
    (event: UiStreamEvent) => {
      switch (event.type) {
        case "text-start": {
          const messageId = asNonEmptyString(event.id);
          if (!messageId) return;
          ensureMessageItem({
            kind: "message",
            id: messageId,
            role: "assistant",
            content: EMPTY_MESSAGE
          });
          return;
        }
        case "text-delta": {
          const messageId = asNonEmptyString(event.id);
          if (!messageId) return;
          updateMessageContent(messageId, asString(event.delta), "assistant");
          return;
        }
        case "text-end":
          return;
        case "reasoning-start": {
          const messageId = asNonEmptyString(event.id);
          if (!messageId) return;
          ensureMessageItem({
            kind: "message",
            id: messageId,
            role: "thinking",
            content: EMPTY_MESSAGE
          });
          return;
        }
        case "reasoning-delta": {
          const messageId = asNonEmptyString(event.id);
          if (!messageId) return;
          updateMessageContent(messageId, asString(event.delta), "thinking");
          return;
        }
        case "reasoning-end":
          return;
        case "tool-input-start": {
          const toolCallId = asNonEmptyString(event.toolCallId);
          if (!toolCallId) return;
          const toolName =
            typeof event.toolName === "string" && event.toolName
              ? event.toolName
              : "tool";
          ensureToolItem(toolCallId, toolName);
          return;
        }
        case "tool-input-delta": {
          const toolCallId = asNonEmptyString(event.toolCallId);
          const delta = asString(event.inputTextDelta);
          if (!toolCallId) return;
          ensureToolItem(toolCallId);
          if (delta) {
            updateToolItem(toolCallId, (item) => ({
              ...item,
              argsRaw: appendToolArgs(item.argsRaw, delta)
            }));
          }
          return;
        }
        case "tool-input-available": {
          const toolCallId = asNonEmptyString(event.toolCallId);
          if (!toolCallId) return;
          const toolName =
            typeof event.toolName === "string" && event.toolName
              ? event.toolName
              : "tool";
          ensureToolItem(toolCallId, toolName);
          setToolArgs(toolCallId, event.input);
          return;
        }
        case "tool-output-available": {
          const toolCallId = asNonEmptyString(event.toolCallId);
          if (!toolCallId) return;
          setToolResult(toolCallId, event.output);
          return;
        }
        case "tool-output-error": {
          const toolCallId = asNonEmptyString(event.toolCallId);
          if (!toolCallId) return;
          const errorText =
            typeof event.errorText === "string" && event.errorText
              ? event.errorText
              : "Tool error";
          setToolResult(toolCallId, { stderr: errorText, exit_code: 1 });
          return;
        }
        case "error": {
          const errorText =
            typeof event.errorText === "string" && event.errorText
              ? event.errorText
              : "Unknown error";
          addSystemMessage(`Run error: ${errorText}`, createId("error"));
          return;
        }
        default:
          return;
      }
    },
    [
      addSystemMessage,
      ensureMessageItem,
      ensureToolItem,
      setToolArgs,
      setToolResult,
      updateMessageContent,
      updateToolItem
    ]
  );

  const hydrateUiMessages = React.useCallback(
    (messages: UiMessage[]) => {
      clearItems();

      const collectText = (parts: UiMessagePart[]) => {
        const chunks: string[] = [];
        for (const part of parts) {
          if (part.type === "text" && typeof part.text === "string") {
            chunks.push(part.text);
            continue;
          }
          const fileLabel = describeFilePart(part);
          if (fileLabel) {
            chunks.push(fileLabel);
          }
        }
        return chunks.join("\n").trim();
      };

      for (const message of messages) {
        if (message.role === "system") {
          const content = collectText(message.parts);
          if (content) {
            addMessage({
              id: message.id || createId("system"),
              role: "system",
              content
            });
          }
          continue;
        }

        if (message.role === "user") {
          const content = collectText(message.parts);
          if (content) {
            addMessage({
              id: message.id || createId("user"),
              role: "user",
              content
            });
          }
          continue;
        }

        if (message.role !== "assistant") {
          continue;
        }

        let buffer = "";
        let usedMessageId = false;

        const flushBuffer = () => {
          if (!buffer.trim()) {
            buffer = "";
            return;
          }
          addMessage({
            id: !usedMessageId && message.id ? message.id : createId("assistant"),
            role: "assistant",
            content: buffer
          });
          usedMessageId = true;
          buffer = "";
        };

        for (const part of message.parts) {
          if (part.type === "text" && typeof part.text === "string") {
            buffer += part.text;
            continue;
          }

          const fileLabel = describeFilePart(part);
          if (fileLabel) {
            buffer += fileLabel;
            continue;
          }

          if (part.type === "reasoning" && typeof part.text === "string") {
            flushBuffer();
            if (part.text.trim()) {
              addMessage({
                id: createId("thinking"),
                role: "thinking",
                content: part.text
              });
            }
            continue;
          }

          if (isUiToolPart(part)) {
            flushBuffer();
            const toolName = extractToolName(part);
            ensureToolItem(part.toolCallId, toolName);
            if (part.input !== undefined) {
              setToolArgs(part.toolCallId, part.input);
            }
            if (part.state === "output-available") {
              setToolResult(part.toolCallId, part.output);
            }
            if (part.state === "output-error") {
              const errorText =
                typeof part.errorText === "string" && part.errorText
                  ? part.errorText
                  : "Tool error";
              setToolResult(part.toolCallId, { stderr: errorText, exit_code: 1 });
            }
          }
        }

        flushBuffer();
      }
    },
    [addMessage, clearItems, ensureToolItem, setToolArgs, setToolResult]
  );

  return {
    items,
    addMessage,
    addSystemMessage,
    handleStreamEvent,
    hydrateUiMessages
  };
}

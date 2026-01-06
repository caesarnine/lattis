import React from "react";

import { type ChatRole } from "@/features/chat/types";
import { createId } from "@/shared/ids";
import { runChatStream } from "@/services/latticeApi";
import { type UiStreamEvent } from "@/services/vercel";

type AddMessageInput = {
  id?: string;
  role: ChatRole;
  content: string;
};

type UseChatStreamParams = {
  sessionId: string | null;
  threadId: string | null;
  addMessage: (input: AddMessageInput) => void;
  onStreamEvent: (event: UiStreamEvent) => void;
};

type ChatStreamPayload = {
  trigger: string;
  id: string;
  messages: {
    id: string;
    role: string;
    parts: { type: "text"; text: string }[];
  }[];
  session_id: string;
  thread_id: string;
};

function buildStreamPayload(
  sessionId: string,
  threadId: string,
  content: string
): ChatStreamPayload {
  return {
    trigger: "submit-message",
    id: createId("run"),
    messages: [
      {
        id: createId("msg"),
        role: "user",
        parts: [
          {
            type: "text",
            text: content
          }
        ]
      }
    ],
    session_id: sessionId,
    thread_id: threadId
  };
}

export function useChatStream({
  sessionId,
  threadId,
  addMessage,
  onStreamEvent
}: UseChatStreamParams) {
  const [isStreaming, setIsStreaming] = React.useState(false);
  const abortRef = React.useRef<AbortController | null>(null);
  const streamIdRef = React.useRef<string | null>(null);
  const threadRef = React.useRef(threadId);

  React.useEffect(() => {
    threadRef.current = threadId;
  }, [threadId]);

  const stop = React.useCallback(() => {
    streamIdRef.current = null;
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  }, []);

  const sendMessage = React.useCallback(
    async (text: string) => {
      if (!sessionId || !threadId || isStreaming) {
        return;
      }

      const trimmed = text.trim();
      if (!trimmed) {
        return;
      }

      addMessage({
        id: createId("user"),
        role: "user",
        content: trimmed
      });

      const streamId = createId("stream");
      streamIdRef.current = streamId;
      setIsStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      const activeThread = threadId;

      try {
        const payload = buildStreamPayload(sessionId, threadId, trimmed);
        const stream = await runChatStream(payload, controller.signal);
        for await (const event of stream) {
          if (streamIdRef.current !== streamId || threadRef.current !== activeThread) {
            controller.abort();
            break;
          }
          onStreamEvent(event);
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          addMessage({
            id: createId("run-error"),
            role: "system",
            content: `Run error: ${
              error instanceof Error ? error.message : String(error)
            }`
          });
        }
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null;
        }
        if (streamIdRef.current === streamId) {
          streamIdRef.current = null;
        }
        setIsStreaming(false);
      }
    },
    [addMessage, isStreaming, onStreamEvent, sessionId, threadId]
  );

  React.useEffect(() => () => abortRef.current?.abort(), []);

  return {
    isStreaming,
    sendMessage,
    stop
  };
}

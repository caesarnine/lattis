export type UiStreamEvent = {
  type: string;
  [key: string]: unknown;
};

export type UiMessagePart =
  | {
      type: "text";
      text: string;
      state?: "streaming" | "done";
      providerMetadata?: Record<string, unknown>;
    }
  | {
      type: "reasoning";
      text: string;
      state?: "streaming" | "done";
      providerMetadata?: Record<string, unknown>;
    }
  | {
      type: "file";
      url: string;
      mediaType: string;
      filename?: string;
      providerMetadata?: Record<string, unknown>;
    }
  | {
      type: `tool-${string}` | "dynamic-tool";
      toolCallId: string;
      toolName?: string;
      state:
        | "input-streaming"
        | "input-available"
        | "output-available"
        | "output-error";
      input?: unknown;
      output?: unknown;
      errorText?: string;
      providerExecuted?: boolean;
      callProviderMetadata?: Record<string, unknown>;
      preliminary?: boolean;
    }
  | {
      type: "step-start";
    }
  | {
      type: `data-${string}`;
      id?: string;
      data: unknown;
      transient?: boolean;
    }
  | {
      type: "source-url";
      sourceId: string;
      url: string;
      title?: string;
      providerMetadata?: Record<string, unknown>;
    }
  | {
      type: "source-document";
      sourceId: string;
      mediaType: string;
      title: string;
      filename?: string;
      providerMetadata?: Record<string, unknown>;
    };

export type UiMessage = {
  id: string;
  role: "system" | "user" | "assistant";
  metadata?: unknown;
  parts: UiMessagePart[];
};

export async function* streamUiEvents(
  response: Response,
  signal?: AbortSignal
): AsyncGenerator<UiStreamEvent> {
  if (!response.body) {
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) {
        try {
          await reader.cancel();
        } catch {
          // ignore cancellation errors
        }
        return;
      }

      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      let boundaryIndex = buffer.indexOf("\n\n");
      while (boundaryIndex !== -1) {
        const chunk = buffer.slice(0, boundaryIndex);
        buffer = buffer.slice(boundaryIndex + 2);

        const lines = chunk.split(/\r?\n/);
        for (const line of lines) {
          if (!line.startsWith("data:")) {
            continue;
          }
          const payload = line.slice(5).trimStart();
          if (!payload || payload === "[DONE]") {
            continue;
          }
          try {
            const parsed = JSON.parse(payload) as UiStreamEvent;
            yield parsed;
          } catch {
            // Ignore malformed payloads.
          }
        }

        boundaryIndex = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

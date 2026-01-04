export type ChatRole =
  | "user"
  | "assistant"
  | "system"
  | "thinking"
  | "developer"
  | "tool"
  | string;

export type ToolResult = {
  output: string;
  exitCode: number;
  timedOut: boolean;
};

export type MessageItem = {
  kind: "message";
  id: string;
  role: ChatRole;
  content: string;
};

export type ToolItem = {
  kind: "tool";
  id: string;
  toolName: string;
  argsRaw: string;
  result?: ToolResult;
};

export type RenderItem = MessageItem | ToolItem;

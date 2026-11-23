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
  status?: string;
};

export type ToolItem = {
  kind: "tool";
  id: string;
  toolName: string;
  argsRaw: string;
  outputStream: string;
  status: "streaming" | "completed" | "error" | "cancelled";
  result?: ToolResult;
};

export type ApprovalItem = {
  kind: "approval";
  id: string;
  runId: string;
  approvalId: string;
  toolName: string;
  args: unknown;
  decision: "approved" | "denied" | null;
  reason?: string | null;
};

export type RenderItem = MessageItem | ToolItem | ApprovalItem;

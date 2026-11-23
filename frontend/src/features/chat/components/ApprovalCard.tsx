import React from "react";
import { Check, ShieldAlert, X } from "lucide-react";

import { type ApprovalItem } from "@/features/chat/types";
import { Button } from "@/shared/ui/button";
import { cn } from "@/shared/utils";

type ApprovalCardProps = {
  item: ApprovalItem;
  onResolve?: (runId: string, approvalId: string, approved: boolean) => Promise<void> | void;
  className?: string;
};

export function ApprovalCard({ item, onResolve, className }: ApprovalCardProps) {
  const [submitting, setSubmitting] = React.useState(false);

  const handleDecision = async (approved: boolean) => {
    if (!onResolve || submitting || item.decision !== null) return;
    setSubmitting(true);
    try {
      await onResolve(item.runId, item.approvalId, approved);
    } finally {
      setSubmitting(false);
    }
  };

  let formattedArgs = "";
  try {
    formattedArgs = JSON.stringify(item.args ?? {}, null, 2);
  } catch {
    formattedArgs = String(item.args ?? "");
  }

  return (
    <div
      className={cn(
        "min-w-0 max-w-full rounded-2xl border border-amber-300/80 bg-amber-50/70 p-4 shadow-sm",
        className
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
          <ShieldAlert size={16} className="text-amber-600" />
          <span>Approval Required: {item.toolName}</span>
        </div>
        {item.decision ? (
          <span
            className={cn(
              "rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest",
              item.decision === "approved"
                ? "bg-emerald-100 text-emerald-700"
                : "bg-rose-100 text-rose-700"
            )}
          >
            {item.decision}
          </span>
        ) : (
          <span className="rounded-full bg-amber-200/70 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-amber-800">
            Pending
          </span>
        )}
      </div>

      {formattedArgs && formattedArgs !== "{}" ? (
        <pre className="mt-3 max-h-48 overflow-auto rounded-xl border border-amber-200/70 bg-white/80 p-3 font-mono text-[11px] text-ink-800">
          {formattedArgs}
        </pre>
      ) : null}

      {item.decision === null ? (
        <div className="mt-3 flex items-center gap-2">
          <Button
            size="sm"
            className="rounded-xl bg-emerald-600 text-white hover:bg-emerald-700"
            disabled={submitting}
            onClick={() => handleDecision(true)}
          >
            <Check size={14} className="mr-1" />
            Approve
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="rounded-xl border-rose-300 text-rose-700 hover:bg-rose-50"
            disabled={submitting}
            onClick={() => handleDecision(false)}
          >
            <X size={14} className="mr-1" />
            Deny
          </Button>
        </div>
      ) : null}
    </div>
  );
}

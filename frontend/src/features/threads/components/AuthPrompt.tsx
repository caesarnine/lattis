import React from "react";
import { KeyRound } from "lucide-react";

import { Button } from "@/shared/ui/button";
import { Input } from "@/shared/ui/input";

type AuthPromptProps = {
  serverUrl: string;
  errorMessage?: string | null;
  onSubmit: (token: string) => void;
};

export function AuthPrompt({ serverUrl, errorMessage, onSubmit }: AuthPromptProps) {
  const [token, setToken] = React.useState("");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = token.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md space-y-5 rounded-3xl border border-ink-200/80 bg-white/90 p-8 shadow-soft"
      >
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-teal-50 text-teal-600 border border-teal-100">
            <KeyRound size={20} />
          </div>
          <div>
            <div className="text-xs font-semibold uppercase tracking-[0.25em] text-ink-500">
              Lattis Daemon
            </div>
            <h1 className="text-xl font-display text-ink-900">Connect with Token</h1>
          </div>
        </div>

        <p className="text-xs leading-relaxed text-ink-500">
          This daemon requires a Bearer token (found in{" "}
          <code className="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-ink-800">
            ~/.lattis/auth.token
          </code>
          ). Target: <span className="font-mono text-ink-700">{serverUrl}</span>
        </p>

        {errorMessage ? (
          <div className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {errorMessage}
          </div>
        ) : null}

        <Input
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Paste bearer token…"
          autoFocus
        />

        <Button
          type="submit"
          className="w-full rounded-2xl bg-ink-900 py-5 text-white hover:bg-ink-800"
          disabled={!token.trim()}
        >
          Connect
        </Button>
      </form>
    </div>
  );
}

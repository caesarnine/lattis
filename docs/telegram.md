Telegram Bridge
===============

`lattis telegram` lets Telegram users chat with Lattis agents using the same
thread storage used by the TUI and web UI.

How thread mapping works
------------------------

- One Telegram chat maps to one persistent Lattis thread.
- Session id defaults to the connected server's session id (same session used by
  TUI/Web by default). Override with `--session-id` or
  `LATTIS_TELEGRAM_SESSION_ID`.
- Thread id is generated as `<thread-prefix>-<chat-id>` where the default
  prefix is `tg` (override with `--thread-prefix` or
  `LATTIS_TELEGRAM_THREAD_PREFIX`).

This gives each chat a cohesive "single texting thread" history.

Run
---

```bash
# Single command stack (server + scheduler + Telegram if token is set)
export LATTIS_TELEGRAM_BOT_TOKEN=...
uvx lattis up

# Or run components separately:
export LATTIS_TELEGRAM_BOT_TOKEN=...
uvx lattis server
uvx lattis telegram --server http://127.0.0.1:8000
```

You can also omit `--server` to reuse auto-discovery/local-server behavior,
similar to `lattis tui`.

Commands inside Telegram
------------------------

- `/start` or `/help` shows bridge help.
- `/clear` (or `/reset`) clears that chat's mapped Lattis thread.

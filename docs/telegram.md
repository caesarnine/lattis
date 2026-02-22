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
- Mapping is stored explicitly as a channel binding in SQLite (`channel=telegram`,
  `external_conversation_id=<chat-id>`), so thread ids are decoupled from Telegram ids.

This gives each chat a cohesive "single texting thread" history while keeping
routing extensible for future channels via the channel adapter registry.

Supported inputs include:

- text messages
- photos/images (with optional caption)
- voice/audio messages
- videos/video notes
- documents (treated as file inputs)

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

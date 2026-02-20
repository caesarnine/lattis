Scheduling Architecture
=======================

Lattis scheduling is intentionally split into two responsibilities:

- The server owns thread state and schedule records in SQLite.
- A separate `lattis scheduler` worker claims due schedules, runs agents, and
  sends proactive delivery (currently Telegram-mapped threads).

This keeps the runtime focused and follows a small-process Unix-style model.

Agent tools
-----------

Built-in agents expose these pydantic-ai tools:

- `schedule_create(prompt, due_at, interval_seconds=None)`
- `schedule_list(include_terminal=False, limit=20)`
- `schedule_update(schedule_id, prompt=None, due_at=None, interval_seconds=None, clear_recurrence=False)`
- `schedule_cancel(schedule_id)`

`due_at` must be ISO-8601 with timezone offset (for example
`2026-02-19T09:00:00-05:00`).

Recurrence
----------

Recurrence is interval-based:

- one-shot: `interval_seconds=None`
- recurring: `interval_seconds > 0`

When a recurring schedule runs, the next due time is advanced forward from the
previous due time until it lands in the future. This avoids backlog replay when
the worker was offline.

Worker command
--------------

Run continuously:

```bash
uvx lattis scheduler
```

Run one claim-and-execute pass:

```bash
uvx lattis scheduler --once
```

Useful flags:

- `--poll-interval`
- `--claim-limit`
- `--lease-seconds`
- `--retry-seconds`

Proactive Telegram delivery
---------------------------

If a schedule belongs to a Telegram-mapped thread id (`tg-...` by default), the
scheduler sends the resulting assistant message to Telegram.

- Bot token is read from `LATTIS_TELEGRAM_BOT_TOKEN` (or `--telegram-token`).
- Thread prefix is `tg` by default (or `--telegram-thread-prefix`).

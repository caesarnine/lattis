Scheduling Architecture
=======================

Lattis scheduling is split into two small responsibilities:

- The server owns schedule and thread state in SQLite.
- A separate `lattis scheduler` worker claims due schedules and executes agent runs.

Scheduled runs are **ephemeral by default**: internal trigger chatter and tool calls are not
written to the main thread history.

Agent Tools
-----------

Built-in agents expose thread-level schedule management tools:

- `schedule_create(prompt, due_at=None, delay_seconds=None, interval_seconds=None)`
- `schedule_list(include_terminal=False, limit=20)`
- `schedule_update(schedule_id, prompt=None, due_at=None, delay_seconds=None, interval_seconds=None, clear_recurrence=False)`
- `schedule_cancel(schedule_id)`
- `current_time()`

`due_at` must be ISO-8601 with timezone offset (for example `2026-02-19T09:00:00-05:00`).
For relative requests ("in 2 minutes"), use `delay_seconds` or call `current_time()` first.

During scheduler-triggered execution, agents also get scheduler-only tools:

- `schedule_state_get()` to read per-schedule state and version.
- `schedule_state_set(state, expected_version=None)` to update state.
- `notify_user(message)` to queue user-visible proactive messages.

Thread History Semantics
------------------------

- If the run does not call `notify_user`, no assistant message is added to thread history.
- Each `notify_user` call appends an assistant message to the thread history.
- Internal run output is captured in schedule run audit records, not the user thread.

Example Prompts
---------------

- "Remind me in 2 minutes to stretch."
- "At 9:00 AM tomorrow, remind me to review payroll."
- "Every 30 minutes, check new email and only notify me if anything is urgent."
- "Move schedule `sched-abc123` to 10 minutes from now."

Recurrence
----------

Recurrence is interval-based:

- one-shot: `interval_seconds=None`
- recurring: `interval_seconds > 0`

When a recurring schedule runs, the next due time is advanced from the prior due timestamp
until it lands in the future. This avoids backlog replay after worker downtime.

State and Run Audit
-------------------

Each schedule includes mutable state:

- `state_json`: arbitrary JSON object (or null)
- `state_version`: optimistic concurrency version

Each execution is recorded in `schedule_runs` with:

- trigger prompt
- run status (`running`, `done`, `failed`)
- result/error text
- number of proactive notifications sent

Worker Command
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

Proactive Telegram Delivery
---------------------------

If a schedule belongs to a Telegram-mapped thread id (`tg-...` by default), each `notify_user`
message is sent to Telegram and appended to thread history.

- Bot token comes from `LATTIS_TELEGRAM_BOT_TOKEN` or `--telegram-token`.
- Thread prefix defaults to `tg` or can be overridden with `--telegram-thread-prefix`.

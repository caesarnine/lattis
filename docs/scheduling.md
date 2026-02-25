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

- `schedule_upsert(prompt, trigger, name=None, enabled=True)`
- `schedule_get(name_or_id)`
- `schedule_list(include_terminal=False, limit=50)`
- `schedule_set_enabled(name_or_id, enabled)`
- `schedule_delete(name_or_id)`
- `current_time()`

Schedules are identified by a stable `name` (recommended) and a generated ID (`sched-...`).

### One-shot schedules

Use `trigger.type="once"` with either:

- `run_at`: ISO-8601 datetime with timezone offset (for example `2026-02-19T09:00:00-05:00`), or
- `delay_seconds`: run N seconds from now

### Cron schedules

Use `trigger.type="cron"` with:

- `cron`: standard 5-field cron (`minute hour day month weekday`) — no seconds
- `timezone`: optional IANA zone (e.g. `America/New_York`) or fixed offset (e.g. `-05:00`); defaults to `UTC`

During scheduler-triggered execution, agents also get scheduler-only tools:

- `schedule_state_get()` to read per-schedule state and version.
- `schedule_state_set(state, expected_version=None)` to update state.
- `notify_user(message)` to queue user-visible proactive messages.

Default Schedules
-----------------

Each thread gets a default periodic schedule named `heartbeat`:

- runs hourly (`cron="0 * * * *"`, `timezone="UTC"`)
- can be edited/disabled
- cannot be deleted (`protected`)

Thread History Semantics
------------------------

- If the run does not call `notify_user`, no assistant message is added to thread history.
- Each `notify_user` call appends an assistant message to the thread history.
- Internal run output is captured in schedule run audit records, not the user thread.

Example Prompts
---------------

- "Remind me in 2 minutes to stretch."
- "At 9:00 AM tomorrow, remind me to review payroll."
- "Every Monday at 9am, check new email and only notify me if anything is urgent."
- "Disable the heartbeat schedule."

Recurrence
----------

Recurrence uses standard 5-field cron.

When a cron schedule runs, the next run is computed as the next cron occurrence **after the
actual completion timestamp**, which avoids backlog replay after worker downtime.

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
- `--outbox-claim-limit`
- `--outbox-lease-seconds`
- `--outbox-retry-seconds`
- `--outbox-max-attempts`

Proactive Delivery
------------------

When a scheduler run calls `notify_user`, messages are written to thread history and
queued in the notification outbox. The scheduler worker then dispatches queued
notifications to bound channel conversations through a channel adapter registry
(telegram today, extensible to additional channels).

For Telegram delivery:

- Bindings are created by `lattis telegram` using channel metadata (`channel=telegram`,
  `external_conversation_id=<chat-id>`).
- Bot token comes from `LATTIS_TELEGRAM_BOT_TOKEN` or `--telegram-token`.

Client Integration Guide
========================

Lattis uses a **Command / Event Bus** architecture designed for thin web, desktop,
mobile, and terminal GUIs. The daemon owns all workspaces, threads, runs, and items;
clients send short REST commands and subscribe to one persistent SSE stream.

Authentication
--------------

All endpoints except `GET /health` require the daemon's Bearer token (stored in
`~/.lattis/auth.token`, or configured via `LATTIS_API_TOKEN`):

- Header: `Authorization: Bearer <token>`
- Query fallback (for browser `EventSource`): `?token=<token>`

Core Flow
---------

1. **Discover or register workspaces**
   - `GET /workspaces` — lists `global` plus all registered project folders.
   - `POST /workspaces` with `{"root_path": "/path/to/repo", "name": "optional"}` — idempotently registers or returns a workspace.
2. **Subscribe to the SSE Event Bus**
   - `GET /events` (optionally `?workspace_id=...&thread_id=...&after_seq=0`, supports `Last-Event-ID`).
   - Streams typed `LattisEvent` JSON frames:
     - `workspace.created` / `workspace.updated` / `workspace.deleted`
     - `thread.created` / `thread.updated` / `thread.deleted` / `thread.cleared`
     - `run.started` / `run.waiting_approval` / `run.completed` / `run.cancelled` / `run.failed`
     - `item.created` / `item.delta` (`text`, `reasoning`, `tool_input`, `tool_output`) / `item.completed`
     - `plugin.state_updated`
     - `bus.resync_required` (re-fetch REST state if a client fell behind the ring buffer)
3. **List / create / configure threads**
   - `GET /workspaces/{wid}/threads`
   - `POST /workspaces/{wid}/threads` (`{"title"?, "agent_id"?, "model"?}`)
   - `GET /threads/{tid}` / `PATCH /threads/{tid}` / `DELETE /threads/{tid}` / `POST /threads/{tid}/clear`
   - `GET /threads/{tid}/models` — available models for the thread's active agent
   - `GET /threads/{tid}/items?after_seq=0&limit=200` — paginated normalized timeline
4. **Start, cancel, and approve runs**
   - `POST /threads/{tid}/runs` with `{"input": "..."}` → `202 Accepted` `{run, user_item}` (`409` if thread already busy)
   - `POST /runs/{rid}/cancel` — cooperatively cancels the background run
   - `POST /runs/{rid}/approvals/{aid}` with `{"approved": true|false, "reason"?: "..."}` — resolves a `DeferredToolRequests` pause
5. **Inspect workspace files, Git diffs & plugin state**
   - `GET /workspaces/{wid}/files?path=&include_hidden=false`
   - `GET /workspaces/{wid}/file?path=<rel_path>`
   - `GET /workspaces/{wid}/git/status`
   - `GET /workspaces/{wid}/git/diff?path=<optional>&staged=false`
   - `GET /workspaces/{wid}/plugins/{agent_id}/state`

Using `@lattis/client` (TypeScript)
-----------------------------------

See `sdk/README.md` for the zero-dependency TypeScript SDK generated from OpenAPI:

```ts
import { LattisClient } from "@lattis/client";

const client = new LattisClient({
  baseUrl: "http://127.0.0.1:7700",
  token: process.env.LATTIS_API_TOKEN
});

const ws = await client.registerWorkspace("/path/to/repo");
const thread = await client.createThread(ws.id);

const controller = new AbortController();
void client.subscribeEvents({
  workspaceId: ws.id,
  signal: controller.signal,
  onEvent: (event) => {
    if (event.type === "item.delta") {
      process.stdout.write(event.data.delta);
    }
  }
});

await client.startRun(thread.id, "Check git status and summarize changes.");
```

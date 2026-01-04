Client Integration Guide
========================

This guide describes the thin-client API flow. The server owns session and thread
state; clients fetch state and send small updates.

Core flow
---------

1. Bootstrap a session and pick the active thread.
   - `GET /session/bootstrap`
   - Optional: `?thread_id=<id>` to request a specific thread.
2. Load the current thread state.
   - `GET /sessions/{session_id}/threads/{thread_id}/state`
   - Returns agent selection, model selection, and message history.
3. Update state when the user changes agent or model.
   - `PATCH /sessions/{session_id}/threads/{thread_id}/state`
   - Body supports `{"agent": "<id-or-name>"}` and/or `{"model": "<name>"}`.
   - Set a field to `null` to reset to the default.
4. Fetch model options for the active thread.
   - `GET /sessions/{session_id}/threads/{thread_id}/models`
   - This is thread-scoped because agents can supply different model lists.
5. Stream responses for a user message.
   - `POST /ui/chat` (Vercel AI stream protocol)
   - Include `session_id` and `thread_id` in the run input payload.

Thread management
-----------------

- List threads: `GET /sessions/{session_id}/threads`
- Create thread: `POST /sessions/{session_id}/threads` with `{"thread_id": "<id>"}` (optional)
- Delete thread: `DELETE /sessions/{session_id}/threads/{thread_id}`
- Clear thread: `POST /sessions/{session_id}/threads/{thread_id}/clear`

Agent discovery
---------------

- List agents: `GET /agents`
- The thread state response includes both the current agent and the default agent.

Minimal fetch sketch
--------------------

```ts
const bootstrap = await fetch("/session/bootstrap").then((res) => res.json());
const { session_id, thread_id } = bootstrap;

const state = await fetch(
  `/sessions/${session_id}/threads/${thread_id}/state`
).then((res) => res.json());

await fetch(`/sessions/${session_id}/threads/${thread_id}/state`, {
  method: "PATCH",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ agent: "lattice" })
});
```

Lattice Web UI
===============

The web UI is a React app that talks to the Lattice server over the Vercel AI UI stream.
It shares sessions/threads with the TUI, so you can switch between clients.

---

## Requirements

- Node 18+
- Lattice server running locally or remotely

---

## Install & Run

```bash
cd frontend
npm install
npm run dev
```

By default it targets `http://localhost:8000`.
To point at a different server, create `frontend/.env.local`:

```bash
VITE_LATTICE_SERVER_URL=http://your-server:8000
```

---

## Usage Notes

- The sidebar includes an **Agent** selector and a **Model** selector (lazy-loaded + searchable).
- The header shows the active model and streaming status.
- Threads and history are shared with the TUI.
- Streaming uses `POST /ui/chat` (Vercel AI data stream protocol).
- History and selections load from `GET /sessions/{session_id}/threads/{thread_id}/state`.
- Agent/model updates use `PATCH /sessions/{session_id}/threads/{thread_id}/state`.
- Model lists come from `GET /sessions/{session_id}/threads/{thread_id}/models`.

## OpenAPI Types

The web client uses types generated from the server's OpenAPI schema:

```bash
cd frontend
npm run gen:openapi
```

---

## Troubleshooting

- **Model errors**: If a model's API key isn't set on the server, the UI will surface a clear error.
- **CORS**: If you host the UI separately, ensure the server is reachable and CORS is allowed.

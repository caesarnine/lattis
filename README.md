# Lattice

Lattice is a pluggable agent toolkit built on **pydantic-ai**: a FastAPI server with a Textual TUI and a bundled web UI.
Agents are loaded as plugins, and each thread can select a different agent.

## What you get

- **Server + clients**: FastAPI API, Textual TUI, and a web UI (served by the same server).
- **Pluggable agents**: built-ins, third-party entry points, or local `module:attribute` specs.
- **Per-thread agent selection**: pick an agent per thread (TUI + web UI + API).
- **Persistent state**: thread history in SQLite, plus a workspace directory for agents that write files/tools.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.14+ (uv can install it automatically)
- An API key for at least one model provider (Gemini, Anthropic, OpenAI, etc.)

## Quick start

```bash
uv sync
uv run lattice
```

Run the server (API + web UI):

```bash
uv run lattice server
```

Then open `http://localhost:8000`.

## CLI

```bash
lattice                 # Run the TUI (default)
lattice tui             # Run the TUI explicitly
lattice server          # Run the API server (and web UI, if built)
```

### `lattice tui`

```
--server <url>          Connect to a specific server URL
--local                 Force local mode (skip server auto-discovery)
--agent <id|name>       Default agent for local/in-process mode
--agents <specs>        Extra plugins (comma-separated `module:attr` specs) for local/in-process mode
```

By default, the TUI auto-discovers a server on `http://127.0.0.1:8000` and connects if it matches the current project;
otherwise it runs in local (in-process) mode.

### `lattice server`

```
--host <host>           Host interface to bind (default: 127.0.0.1)
--port <port>           Port to bind (default: 8000)
--reload                Enable auto-reload
--workspace             Workspace mode: local | central
--agent <id|name>       Default agent id or name
--agents <specs>        Extra plugins (comma-separated `module:attr` specs)
```

## Agents

Built-in agents:

- `lattice` — a script-building developer agent that can write reusable, composable tools
- `poetry` — a simple example agent

### Select an agent per thread

- **TUI**: use `/agent`, `/agent list`, `/agent set <id|number>`, `/agent default`
- **Web UI**: use the sidebar agent selector
- **API**: `PATCH /sessions/{session_id}/threads/{thread_id}/state` with `{"agent": "<id-or-name>"}` (or `null` to reset)

### Client integration

See `docs/client-integration.md` for the thin-client API flow (bootstrap, thread state, model options, streaming).

### Add your own agent plugins

Lattice discovers agents automatically from:

1. `lattice.agents.builtins` (included with Lattice)
2. Python entry points in the group **`lattice.agents`**
3. Extra `module:attribute` specs via `AGENT_PLUGINS` / `--agents`

Entry point example (`pyproject.toml` in your plugin package):

```toml
[project.entry-points."lattice.agents"]
my-agent = "my_package.my_agent:plugin"
```

Your `plugin` can be:

- an `AgentPlugin`, or
- a `pydantic_ai.Agent`, or
- a callable that returns an `Agent` (optionally taking `model`).

## Storage

Workspace modes:

- `local` (default): per-project `.lattice/` under the current directory
- `central`: `~/.lattice/`

Typical layout:

```
.lattice/
  lattice.db
  session_id
  workspace/
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LATTICE_MODEL` | *(unset)* | Default model name (also read from `AGENT_MODEL`) |
| `AGENT_DEFAULT` | `lattice` | Default agent id/name (server + local mode) |
| `AGENT_PLUGINS` | *(unset)* | Extra plugins (`module:attr`, comma-separated) |
| `LATTICE_WORKSPACE_MODE` | `local` | `local` (per-project) or `central` (`~/.lattice`) |
| `LATTICE_SERVER_URL` | *(unset)* | Server URL for clients that connect over HTTP |
| `LATTICE_LOGFIRE` | `0` | Enable Logfire telemetry (used by the built-in `lattice` agent) |
| `LATTICE_GLOBAL_BIN` | *(unset)* | Where the built-in `lattice` agent can symlink tools for global use |
| `LATTICE_PROJECT_ROOT` | *(cwd)* | Project root used for `local` storage mode |
| `LATTICE_DATA_DIR` | *(derived)* | Override the data directory |
| `LATTICE_WORKSPACE_DIR` | *(derived)* | Override the workspace directory |
| `LATTICE_DB_PATH` | *(derived)* | Override the SQLite DB path |
| `LATTICE_SESSION_FILE` | *(derived)* | Override the session id file path |
| `LATTICE_SESSION_ID` | *(unset)* | Force a specific session id |

## Web UI development

The server serves the web UI from `lattice/web/static` when it exists.

```bash
cd frontend
npm install
npm run build
```

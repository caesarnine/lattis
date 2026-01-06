# Lattis

Lattis is a pluggable agent toolkit built on **pydantic-ai**: a FastAPI server with a Textual TUI and a bundled web UI.
Agents are loaded as plugins, and each thread can select a different agent.

## What you get

- **Server + clients**: FastAPI API, Textual TUI, and a web UI (served by the same server).
- **Pluggable agents**: built-ins, third-party entry points, or local `module:attribute` specs.
- **Per-thread agent selection**: pick an agent per thread (TUI + web UI + API).
- **Persistent state**: thread history in SQLite, plus a workspace directory for agents that write files/tools.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.12+ (uv can install it automatically)
- An API key for at least one model provider (Gemini, Anthropic, OpenAI, etc.)

## Quick start

```bash
uv sync
uv run lattis
```

Run the server (API + web UI):

```bash
uv run lattis server
```

Then open `http://localhost:8000`.

## CLI

```bash
lattis                 # Run the TUI (default)
lattis tui             # Run the TUI explicitly
lattis server          # Run the API server (and web UI, if built)
```

### `lattis tui`

```
--server <url>          Connect to a specific server URL
--local                 Force local mode (skip server auto-discovery)
--agent <id|name>       Default agent for local/in-process mode
--agents <specs>        Extra plugins (comma-separated `module:attr` specs) for local/in-process mode
```

By default, the TUI auto-discovers a server on `http://127.0.0.1:8000` and connects if it matches the current project;
otherwise it runs in local (in-process) mode.

### `lattis server`

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

- `assistant` - a general-purpose default agent
- `poetry` - a simple example agent

Optional plugins:

- `binsmith` - a toolkit-focused developer agent; install `binsmith` or run `uvx binsmith`

### Select an agent per thread

- **TUI**: use `/agent`, `/agent list`, `/agent set <id|number>`, `/agent default`
- **Web UI**: use the sidebar agent selector
- **API**: `PATCH /sessions/{session_id}/threads/{thread_id}/state` with `{"agent": "<id-or-name>"}` (or `null` to reset)

### Client integration

See `docs/client-integration.md` for the thin-client API flow (bootstrap, thread state, model options, streaming).

### Add your own agent plugins

Lattis discovers agents automatically from:

1. `lattis.agents.builtins` (included with Lattis)
2. Python entry points in the group **`lattis.agents`**
3. Extra `module:attribute` specs via `AGENT_PLUGINS` / `--agents`

Entry point example (`pyproject.toml` in your plugin package):

```toml
[project.entry-points."lattis.agents"]
my-agent = "my_package.my_agent:plugin"
```

Your `plugin` can be:

- an `AgentPlugin`, or
- a `pydantic_ai.Agent`, or
- a callable that returns an `Agent` (optionally taking `model`).

For frictionless integrations, export a `pydantic_ai.Agent` directly:

```python
from pydantic_ai import Agent

plugin = Agent("google-gla:gemini-3-flash-preview")
```

If you need metadata or hooks, use the public plugin API:

```python
from lattis.plugins import AgentPlugin, list_known_models
```

Or use the helper to wrap an `Agent` or factory:

```python
from pydantic_ai import Agent
from lattis.plugins import plugin_from

plugin = plugin_from(Agent("google-gla:gemini-3-flash-preview"), id="my-agent", name="My Agent")
```

## Storage

Workspace modes:

- `local` (default): per-project `.lattis/` under the current directory
- `central`: `~/.lattis/`

Typical layout:

```
.lattis/
  lattis.db
  session_id
  workspace/
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_DEFAULT` | `assistant` | Default agent id/name (server + local mode) |
| `AGENT_PLUGINS` | *(unset)* | Extra plugins (`module:attr`, comma-separated) |
| `LATTIS_WORKSPACE_MODE` | `local` | `local` (per-project) or `central` (`~/.lattis`) |
| `LATTIS_SERVER_URL` | *(unset)* | Server URL for clients that connect over HTTP |
| `LATTIS_PROJECT_ROOT` | *(cwd)* | Project root used for `local` storage mode |
| `LATTIS_DATA_DIR` | *(derived)* | Override the data directory |
| `LATTIS_WORKSPACE_DIR` | *(derived)* | Override the workspace directory |
| `LATTIS_DB_PATH` | *(derived)* | Override the SQLite DB path |
| `LATTIS_SESSION_FILE` | *(derived)* | Override the session id file path |
| `LATTIS_SESSION_ID` | *(unset)* | Force a specific session id |

## Web UI development

The server serves the web UI from `lattis/web/static` when it exists.

```bash
cd frontend
npm install
npm run build
```

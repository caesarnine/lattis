<p align="center" style="bold">Lattis</p>
<p align="center">
  Self-hosted, single-daemon agent server with a REST + SSE Event Bus API, TypeScript SDK, terminal UI, and web workspace UI.
</p>

<table align="center">
  <tr>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/a0ace246-70db-4c03-be6a-a5077272fa87" width="100%" />
      <br>
      <b>Web Workspace UI</b>
    </td>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/240d00da-ad79-4af8-a101-567869f6121f" width="100%" />
      <br>
      <b>Terminal UI</b>
    </td>
  </tr>
</table>

Lattis runs one always-on local daemon (`~/.lattis/`) that hosts pluggable `pydantic-ai` agents across all your project workspaces. Clients—the bundled Web Workspace UI, the Terminal UI, or your own desktop/mobile GUIs via `@lattis/client`—connect over authenticated REST + a real-time SSE Event Bus so runs stay alive across reloads and stay live-synced across every connected client.

## Quick start

```bash
# Auto-start/attach to the local daemon and open the TUI for the current directory
uvx lattis

# Run the daemon explicitly (API + Web UI on http://127.0.0.1:7700)
uvx lattis daemon

# Attach from another machine
uvx lattis --server http://your-server:7700 --token <bearer-token>
```

## Why Lattis

- **Single daemon, multi-workspace**: Manage `Global` plus any number of local project folders from one SQLite store under `~/.lattis/`
- **Detached background runs + live SSE Event Bus**: Runs survive browser reloads and terminal disconnects; multiple GUIs mirror tokens, live tool output, and thread state in real time
- **Workspace Inspector APIs**: Path-jailed file browsing, file previews, Git status, and unified diffs built in
- **Pluggable `pydantic-ai` agents**: Per-thread agent and model selection, `DeferredToolRequests` human-in-the-loop approvals, and plugin-provided state panels (e.g., Binsmith’s Toolkit)
- **OpenAPI-first + `@lattis/client` SDK**: Auto-generated TypeScript types for both REST and the `LattisEvent` union (`sdk/`)
- **Secure by default**: Auto-generated `0600` Bearer token (`~/.lattis/auth.token`) and locked-down CORS

## Mental model

```text
Daemon (~/.lattis/)
 ├── Agents (built-ins + entry points + --agents specs)
 └── Workspaces (Global + registered project directories)
      └── Threads (title, per-thread agent & model, status)
           ├── Runs (detached background tasks, cancel, approvals, usage)
           └── Items (normalized user/assistant/reasoning/tool/approval timeline)
```

- **Commands** are short REST calls (`POST /threads/{id}/runs` returns `202 Accepted`, `POST /runs/{id}/cancel`, `POST /runs/{id}/approvals/{aid}`).
- **Observations** flow over `GET /events` (SSE with monotonic `seq`, `Last-Event-ID` replay, and workspace/thread filtering).

See [docs/client-integration.md](docs/client-integration.md) and [sdk/README.md](sdk/README.md) for building custom GUIs against the daemon.

## Agents

Lattis discovers agents from:

1. Built-ins: `assistant`, `poetry`
2. Entry points: packages registering `lattis.agents` (e.g. [Binsmith](https://github.com/caesarnine/binsmith))
3. Explicit specs: `module:attr` via `--agents` or `AGENT_PLUGINS`

Simple agent using `pydantic-ai`:

```python
# my_agent.py
from pydantic_ai import Agent

plugin = Agent("google-gla:gemini-3-flash-preview", system_prompt="You are helpful.")
```

```bash
uvx lattis daemon --agents my_agent:plugin
```

Full plugin with custom deps, live tool output streaming, and GUI state panel:

```python
from pydantic_ai import Agent
from lattis.plugins import AgentPlugin, AgentRunContext, PluginStateContext

def create_agent(model: str) -> Agent:
    return Agent(model, system_prompt="...")

def create_deps(ctx: AgentRunContext):
    # Access ctx.project_root, ctx.plugin_data_dir, ctx.workspace_data_dir,
    # ctx.emit_tool_output(tool_call_id, chunk, stream), ctx.notify_state_changed()
    return MyDeps(...)

def get_state(ctx: PluginStateContext) -> dict:
    return {"status": "ready"}

plugin = AgentPlugin(
    id="my-agent",
    name="My Agent",
    create_agent=create_agent,
    create_deps=create_deps,
    get_state=get_state,
)
```

Register via entry point in `pyproject.toml`:

```toml
[project.entry-points."lattis.agents"]
my-agent = "my_package:plugin"
```

## CLI

```bash
lattis                 # TUI (auto-starts/attaches to daemon for current directory)
lattis tui --global    # TUI attached to the Global workspace
lattis daemon          # Run the daemon (API + Web UI on 127.0.0.1:7700)
lattis server          # Alias for `lattis daemon`
```

Common options:

```text
--host <host>      Bind host for daemon (default: 127.0.0.1)
--port <port>      Bind port for daemon (default: 7700)
--cors <origins>   Comma-separated allowed CORS origins
--no-auth          Disable Bearer token auth (local dev only)
--server <url>     Connect TUI to a remote daemon
--token <token>    Bearer token (defaults to ~/.lattis/auth.token)
--agent <id>       Default agent
--agents <specs>   Extra plugins (comma-separated module:attr)
```

## Storage layout

```text
~/.lattis/
  lattis.db          # Workspaces, threads, runs, items, model messages (SQLite WAL)
  daemon.json        # Active daemon PID, host, port, API URL
  auth.token         # Auto-generated Bearer token (chmod 600)
  plugins/<id>/      # Global persistent data directory per plugin
  workspaces/        # Backing directory for Global + per-workspace plugin data
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LATTIS_HOME` | `~/.lattis` | Daemon home directory |
| `LATTIS_SERVER_URL` | | Remote daemon URL for TUI |
| `LATTIS_API_TOKEN` | | Override Bearer token |
| `LATTIS_CORS_ORIGINS` | | Comma-separated allowed CORS origins |
| `LATTIS_NO_AUTH` | `0` | Disable authentication (`1`/`true`) |
| `AGENT_DEFAULT` | `assistant` | Default agent |
| `AGENT_MODEL` | | Fallback default model |
| `AGENT_PLUGINS` | | Extra plugins (comma-separated `module:attr`) |

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended)
- An API key for at least one model provider (Gemini, Anthropic, OpenAI)

```bash
export GEMINI_API_KEY=...     # Google
export ANTHROPIC_API_KEY=...  # Anthropic
export OPENAI_API_KEY=...     # OpenAI
```

## Web UI & SDK development

```bash
# Build the bundled Web Workspace UI (also regenerates OpenAPI types)
cd frontend
npm install
npm run build

# Build the standalone @lattis/client TypeScript SDK
cd ../sdk
npm run build
```

Static files are served automatically from `lattis/web/static` when built.

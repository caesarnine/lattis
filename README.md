<h1 align="center">Lattis</h1>
<p align="center">
  A local daemon for running <code>pydantic-ai</code> agents, with a TUI, Web UI, and TypeScript client.
</p>

<table align="center">
  <tr>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/a0ace246-70db-4c03-be6a-a5077272fa87" width="100%" />
      <br>
      <b>Web UI</b>
    </td>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/240d00da-ad79-4af8-a101-567869f6121f" width="100%" />
      <br>
      <b>Terminal UI</b>
    </td>
  </tr>
</table>

If you build a `pydantic-ai` agent and want to actually use it day to day, you end up writing the same plumbing every time: SQLite thread storage, streaming, tool approvals, a UI, and a way to jump between repos without losing state.

Lattis handles that layer. One local daemon under `~/.lattis/` owns your workspaces, threads, and background runs. You connect from the TUI, the bundled Web UI (which includes a workspace file browser and `git diff` viewer), or your own frontend. If you close a browser tab or lose SSH, runs keep going in the background and catch you up when you reconnect.

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

Built-in agents default to `google-gla:gemini-3-flash-preview`:

```bash
export GOOGLE_API_KEY=...
uvx lattis
```

Using Anthropic or OpenAI instead? Set `AGENT_MODEL` (or switch models live in the TUI with `/model set`):

```bash
export ANTHROPIC_API_KEY=...
export AGENT_MODEL=anthropic:claude-sonnet-4-5
uvx lattis
```

Running `uvx lattis` auto-starts the local daemon if one isn't running yet and opens the TUI for your current directory. Inside the TUI, use `/help`, `/threads`, `/thread new`, `/agent`, `/model`, and `/clear` to navigate.

To run the daemon in the foreground instead (serving the API and Web UI on `http://127.0.0.1:7700`):

```bash
uvx lattis daemon
```

Auth is on by default. When you open `http://127.0.0.1:7700`, paste the Bearer token from `~/.lattis/auth.token` (or pass `--no-auth` during local testing):

```bash
cat ~/.lattis/auth.token
```

To use Lattis with a plugin like [Binsmith](https://github.com/caesarnine/binsmith) in the same environment:

```bash
uv tool install lattis --with binsmith
# or one-off:
uvx --with binsmith lattis
```

## How it works

```text
~/.lattis/ (one daemon)
 ├── Agents      built-ins, installed entry points, or --agents specs
 └── Workspaces  "global" + registered project directories
      └── Threads  title, agent, model, status
           ├── Runs   background asyncio tasks (cancelable, resumable approvals)
           └── Items  messages, reasoning, tool calls, and approval requests
```

- Clients send short REST calls to mutate state (`POST /threads/{id}/runs`, `POST /runs/{id}/cancel`, `POST /runs/{id}/approvals/{aid}`) and subscribe to one SSE stream (`GET /events`) with `Last-Event-ID` replay.
- You can switch agents or models per thread, stream tool stdout/stderr live, and resolve `pydantic-ai` deferred tool approval prompts in the Web UI (or via the API; the TUI prints a notice when approval is pending).
- Everything persists in SQLite (`~/.lattis/lattis.db`), so opening the TUI and Web UI side by side mirrors the same runs in real time.

If you're putting your own frontend in front of the daemon, see [docs/client-integration.md](docs/client-integration.md) and the OpenAPI-typed TypeScript SDK in [sdk/README.md](sdk/README.md).

## Writing an agent

Lattis discovers agents from three sources:

1. Built-ins: `assistant` and `poetry`
2. Installed packages exposing the `lattis.agents` entry point (like [Binsmith](https://github.com/caesarnine/binsmith))
3. Explicit `module:attr` specs via `--agents` or `AGENT_PLUGINS`

The smallest plugin is a function that takes a model name and returns a `pydantic-ai` `Agent`:

```python
# my_agent.py
from pydantic_ai import Agent

def my_agent(model: str) -> Agent:
    return Agent(model, system_prompt="You are helpful.")
```

Load it from the current directory with `PYTHONPATH=.` (a bare `Agent(...)` instance also works, though it locks the model and skips per-thread model switching):

```bash
PYTHONPATH=. uvx lattis daemon --agents my_agent:my_agent
```

For per-run dependencies, live tool output streaming, or a custom state panel in the Web UI, wrap it in `AgentPlugin`:

```python
from pydantic_ai import Agent
from lattis.plugins import AgentPlugin, AgentRunContext, PluginStateContext

def create_agent(model: str) -> Agent:
    return Agent(model, system_prompt="...")

def create_deps(ctx: AgentRunContext):
    # ctx exposes project_root, plugin_data_dir, workspace_data_dir,
    # emit_tool_output(tool_call_id, chunk, stream), and notify_state_changed().
    return MyDeps(root=ctx.project_root)

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

To make a packaged agent show up automatically when installed, register an entry point in `pyproject.toml`:

```toml
[project.entry-points."lattis.agents"]
my-agent = "my_package:plugin"
```

## Remote usage

Run the daemon on an always-on host (ideally behind Tailscale or a VPN) and copy the token from the server's `~/.lattis/auth.token`:

```bash
# On the server
uvx lattis daemon --host 0.0.0.0 --port 7700

# From another machine (TUI)
uvx lattis --server http://your-server:7700 --token <token-from-server>

# Or open http://your-server:7700 in a browser for the Web UI
```

## CLI

```bash
lattis                 # Open TUI for the current directory (auto-starts daemon if needed)
lattis tui --global    # Open TUI attached to the global workspace
lattis daemon          # Run the daemon in the foreground (API + Web UI on :7700)
lattis server          # Alias for `lattis daemon`
```

Daemon options (`lattis daemon` / `lattis server`):

```text
--host <host>      Bind host (default: 127.0.0.1)
--port <port>      Bind port (default: 7700)
--cors <origins>   Comma-separated allowed CORS origins (default: same-origin only)
--no-auth          Disable Bearer token auth (local dev only)
--reload           Auto-reload daemon on code changes
--agent <id>       Default agent id or name
--agents <specs>   Extra plugins (comma-separated module:attr)
```

TUI options (`lattis` / `lattis tui`):

```text
--server <url>     Connect to a remote daemon
--token <token>    Bearer token (falls back to local ~/.lattis/auth.token)
--global           Attach to the global workspace instead of cwd
--agent <id>       Default agent for new threads (and auto-started daemon)
--agents <specs>   Extra plugins (only applied when auto-starting a new daemon)
```

Note: `uvx lattis` spawns the daemon in the background and writes its PID to `~/.lattis/daemon.json`. When iterating on plugins or flags, run `lattis daemon` in a terminal so you can see logs and restart with Ctrl-C (or stop a background daemon via the PID in `daemon.json`).

## Storage & configuration

```text
~/.lattis/
  lattis.db          # Workspaces, threads, runs, items, and message history (SQLite WAL)
  daemon.json        # Running daemon PID, host, port, and URL
  auth.token         # Generated Bearer token (chmod 600)
  plugins/<id>/      # Shared persistent directory per plugin
  workspaces/        # Backing directory for global + per-workspace plugin data
```

| Variable | Default | Description |
|----------|---------|-------------|
| `LATTIS_HOME` | `~/.lattis` | Daemon home directory |
| `LATTIS_SERVER_URL` | | Remote daemon URL for the TUI |
| `LATTIS_API_TOKEN` | | Override the Bearer token |
| `LATTIS_CORS_ORIGINS` | | Comma-separated allowed CORS origins |
| `LATTIS_NO_AUTH` | `0` | Disable auth (`1`/`true`) |
| `AGENT_DEFAULT` | `assistant` | Default agent |
| `AGENT_MODEL` | `google-gla:gemini-3-flash-preview` | Default model for built-in agents (and fallback for plugins) |
| `AGENT_PLUGINS` | | Extra plugins (comma-separated `module:attr`) |

## Developing the Web UI & SDK

End users don't need Node; prebuilt Web UI assets ship in `lattis/web/static`. To rebuild them from source:

```bash
# Rebuild the Web UI (also regenerates OpenAPI types)
cd frontend
npm install
npm run build

# Regenerate OpenAPI types and build @lattis/client (see sdk/README.md)
cd ../sdk
npm run gen:openapi && npm run build
```

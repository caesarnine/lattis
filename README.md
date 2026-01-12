<p align="center" style="bold">Lattis</p>
<p align="center">
  Self-hosted agent server with a terminal UI, web UI, and persistent threads.
</p>

<table align="center">
  <tr>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/a0ace246-70db-4c03-be6a-a5077272fa87" width="100%" />
      <br>
      <b>Terminal UI</b>
    </td>
    <td align="center">
      <img src="https://github.com/user-attachments/assets/240d00da-ad79-4af8-a101-567869f6121f" width="100%" />
      <br>
      <b>Web UI</b>
    </td>
  </tr>
</table>

Lattis runs the agents on a server. Clients (TUI or browser) connect over HTTP. Threads live in SQLite so you can start on one device and continue on another.

## Quick start

```bash
# Local server + TUI
uvx lattis

# Server only
uvx lattis server
# Then open http://localhost:8000

# Connect from another machine
uvx lattis --server http://your-server:8000
```

## Why Lattis

- Persistent threads stored in SQLite under `.lattis/`
- TUI-first workflow with a bundled web UI
- Pluggable agents and per-thread agent selection
- Local-first storage, no hosted service required

## Mental model

- The server owns threads, messages, and storage
- Clients are just views into a thread
- Each thread has an agent and model; you can switch either at any time

## Agents

Lattis discovers agents from:

1. Built-ins: `assistant`, `poetry`
2. Entry points: packages that register `lattis.agents`
3. Explicit specs: `module:attr` via `--agents` or `AGENT_PLUGINS`

Simple agent using `pydantic-ai`:

```python
# my_agent.py
from pydantic_ai import Agent

plugin = Agent("google-gla:gemini-2.0-flash", system_prompt="You are helpful.")
```

```bash
uvx lattis --agents my_agent:plugin
```

Full plugin with custom dependencies:

```python
from pydantic_ai import Agent
from lattis.plugins import AgentPlugin, AgentRunContext

def create_agent(model: str) -> Agent:
    return Agent(model, system_prompt="...")

def create_deps(ctx: AgentRunContext):
    # Access ctx.workspace, ctx.project_root, ctx.session_id, etc.
    return MyDeps(...)

plugin = AgentPlugin(
    id="my-agent",
    name="My Agent",
    create_agent=create_agent,
    create_deps=create_deps,
)
```

Register via entry point in `pyproject.toml`:

```toml
[project.entry-points."lattis.agents"]
my-agent = "my_package:plugin"
```

## CLI

```bash
lattis                 # TUI (starts a local server)
lattis tui             # TUI explicitly
lattis server          # API server + web UI
```

Common options:

```
--server <url>     Connect to a remote server
--agent <id>       Default agent
--agents <specs>   Extra plugins (comma-separated module:attr)
```

## Storage layout

```
.lattis/
  lattis.db          # Threads, messages, state (SQLite)
  session_id         # Persistent session identifier
  workspace/         # Shared directory for agent tools/data
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_DEFAULT` | `assistant` | Default agent |
| `AGENT_PLUGINS` | | Extra plugins (comma-separated `module:attr`) |
| `LATTIS_SERVER_URL` | | Server URL for remote connections |
| `LATTIS_PROJECT_ROOT` | cwd | Project root for storage |
| `LATTIS_DATA_DIR` | `.lattis` | Data directory |
| `LATTIS_WORKSPACE_DIR` | | Override workspace location |

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended)
- An API key for at least one model provider (Gemini, Anthropic, OpenAI)

```bash
export GEMINI_API_KEY=...     # Google
export ANTHROPIC_API_KEY=...  # Anthropic
export OPENAI_API_KEY=...     # OpenAI
```

## Web UI development

```bash
cd frontend
npm install
npm run build
```

Static files are served from `lattis/web/static` when present.

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import uvicorn

from lattice.client import AgentClient
from lattice.tui.app import run_tui

DEFAULT_SERVER_URL = os.getenv("LATTICE_SERVER_URL")
DEFAULT_AUTO_DISCOVER_PORT = 8000


@dataclass
class ConnectionInfo:
    """Information about the TUI's connection mode."""

    mode: str  # "server", "local", or "local-server"
    server_url: str | None = None

    @property
    def status_message(self) -> str:
        if self.mode == "server" and self.server_url:
            return f"Connecting to {self.server_url}..."
        if self.mode == "local-server" and self.server_url:
            return f"Starting local server at {self.server_url}..."
        return "Starting in local mode..."

    @property
    def header_label(self) -> str:
        if self.mode == "server" and self.server_url:
            # Extract host:port for display
            parsed = urlparse(self.server_url)
            return f":{parsed.port}" if parsed.port else parsed.netloc
        if self.mode == "local-server" and self.server_url:
            parsed = urlparse(self.server_url)
            if parsed.port:
                return f"local:{parsed.port}"
            return "local"
        return "local"


@dataclass
class SpawnedServer:
    process: subprocess.Popen
    server_url: str

    def shutdown(self, timeout: float = 3.0) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()


@dataclass
class TuiClientContext:
    client: AgentClient
    connection_info: ConnectionInfo
    local_server: SpawnedServer | None = None


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    if argv is None:
        argv = sys.argv[1:]
    argv = list(argv)
    if not argv:
        argv = ["tui"]
    elif argv[0].startswith("-") and argv[0] not in {"-h", "--help"}:
        argv = ["tui", *argv]
    args = parser.parse_args(argv)

    command = args.command or "tui"
    if command == "tui":
        _run_tui_command(args)
        return
    if command == "server":
        _run_server_command(args)
        return

    parser.print_help()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lattice", description="Agent CLI")
    subparsers = parser.add_subparsers(dest="command")

    tui_parser = subparsers.add_parser("tui", help="Run the TUI client")
    _add_tui_args(tui_parser)

    server_parser = subparsers.add_parser("server", help="Run the API server")
    _add_server_args(server_parser)

    return parser


def _add_tui_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--server",
        default=DEFAULT_SERVER_URL,
        help="Connect to a specific server URL",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force local server mode (skip server auto-discovery)",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Default agent id or name for this session (local mode only)",
    )
    parser.add_argument(
        "--agents",
        default=None,
        help="Comma-separated agent plugin specs to load (local mode only)",
    )


def _add_server_args(parser: argparse.ArgumentParser) -> None:
    env_workspace = (os.getenv("LATTICE_WORKSPACE_MODE") or "").strip().lower()
    default_workspace = "central" if env_workspace == "central" else "local"
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload",
    )
    parser.add_argument(
        "--workspace",
        choices=("local", "central"),
        default=default_workspace,
        help="Workspace mode (default: %(default)s)",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Default agent id or name",
    )
    parser.add_argument(
        "--agents",
        default=None,
        help="Comma-separated agent plugin specs to load",
    )


def _run_tui_command(args: argparse.Namespace) -> None:
    project_root = Path.cwd()

    context = _create_tui_client(args, project_root=project_root)
    print(context.connection_info.status_message)
    try:
        run_tui(client=context.client, connection_info=context.connection_info)
    finally:
        if context.local_server:
            context.local_server.shutdown()


def _run_server_command(args: argparse.Namespace) -> None:
    project_root = Path.cwd()
    agent_specs = _parse_agent_specs(getattr(args, "agents", None))
    _apply_server_env_defaults(
        project_root=project_root,
        workspace_mode=args.workspace,
        default_agent=getattr(args, "agent", None),
        agent_specs=agent_specs,
    )

    uvicorn.run("lattice.server.asgi:app", host=args.host, port=args.port, reload=args.reload)


def _normalize_server_url(url: str) -> str:
    if "://" not in url:
        url = f"http://{url}"
    parsed = urlparse(url)
    if not parsed.netloc:
        raise SystemExit(f"Invalid server URL: {url}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _server_healthy(server_url: str) -> bool:
    try:
        response = httpx.get(f"{server_url}/health", timeout=1.0)
    except httpx.RequestError:
        return False
    return response.status_code == 200


def _pick_local_port(host: str) -> int:
    preferred = DEFAULT_AUTO_DISCOVER_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, preferred))
        except OSError:
            pass
        else:
            return preferred

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def _wait_for_server(server_url: str, process: subprocess.Popen, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _server_healthy(server_url):
            return True
        time.sleep(0.1)
    return False


def _spawn_local_server(
    *,
    project_root: Path,
    agent_specs: list[str] | None,
    default_agent: str | None,
) -> SpawnedServer:
    host = "127.0.0.1"
    port = _pick_local_port(host)
    server_url = f"http://{host}:{port}"

    env = _build_server_env(
        project_root=project_root,
        workspace_mode="local",
        default_agent=default_agent,
        agent_specs=agent_specs,
    )

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "lattice.server.asgi:app",
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        "warning",
    ]
    process = subprocess.Popen(
        cmd,
        cwd=str(project_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not _wait_for_server(server_url, process):
        exit_code = process.poll()
        if exit_code is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
            raise SystemExit("Local server failed to start (timeout). Try `lattice server` for logs.")
        raise SystemExit(
            f"Local server failed to start (exit code {exit_code}). Try `lattice server` for logs."
        )

    return SpawnedServer(process=process, server_url=server_url)


def _is_same_project(server_url: str, project_root: Path) -> bool:
    """Check if the server is running for the same project."""
    try:
        info = httpx.get(f"{server_url}/info", timeout=2.0).json()
    except Exception:
        return False

    server_root = info.get("project_root")
    if not isinstance(server_root, str) or not server_root:
        return False

    try:
        expected = project_root.resolve()
        actual = Path(server_root).resolve()
    except OSError:
        return False

    return actual == expected


def _create_tui_client(
    args: argparse.Namespace, *, project_root: Path
) -> TuiClientContext:
    agent_spec = getattr(args, "agent", None)
    agent_specs = _parse_agent_specs(getattr(args, "agents", None))

    # --local flag: skip all discovery, spawn local server
    if getattr(args, "local", False):
        return _start_local_server(
            project_root=project_root,
            agent_specs=agent_specs,
            default_agent=agent_spec,
        )

    # --server URL: explicit connection (no project validation)
    server = getattr(args, "server", None)
    if server:
        server_url = _normalize_server_url(server)
        _ensure_server_healthy(server_url)
        return _build_server_context(server_url)

    # Auto-discovery: check default port, validate project
    auto_url = f"http://127.0.0.1:{DEFAULT_AUTO_DISCOVER_PORT}"
    if _server_healthy(auto_url):
        if _is_same_project(auto_url, project_root):
            return _build_server_context(auto_url)
        # Different project - silently fall back to local

    # Fallback: spawn local server
    return _start_local_server(
        project_root=project_root,
        agent_specs=agent_specs,
        default_agent=agent_spec,
    )


def _parse_agent_specs(value: str | None) -> list[str] | None:
    if not isinstance(value, str):
        return None
    items = [item.strip() for item in value.split(",")]
    filtered = [item for item in items if item]
    return filtered or None


def _apply_server_env_defaults(
    *,
    project_root: Path,
    workspace_mode: str,
    default_agent: str | None,
    agent_specs: list[str] | None,
) -> None:
    os.environ.setdefault("LATTICE_PROJECT_ROOT", str(project_root))
    os.environ.setdefault("LATTICE_WORKSPACE_MODE", workspace_mode)
    if default_agent:
        os.environ["AGENT_DEFAULT"] = str(default_agent)
    if agent_specs:
        os.environ["AGENT_PLUGINS"] = ",".join(agent_specs)


def _build_server_env(
    *,
    project_root: Path,
    workspace_mode: str,
    default_agent: str | None,
    agent_specs: list[str] | None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["LATTICE_PROJECT_ROOT"] = str(project_root)
    env["LATTICE_WORKSPACE_MODE"] = workspace_mode
    if default_agent is not None:
        env["AGENT_DEFAULT"] = str(default_agent)
    if agent_specs is not None:
        env["AGENT_PLUGINS"] = ",".join(agent_specs)
    return env


def _build_server_context(server_url: str) -> TuiClientContext:
    return TuiClientContext(
        client=AgentClient(server_url),
        connection_info=ConnectionInfo(mode="server", server_url=server_url),
    )


def _build_local_server_context(local_server: SpawnedServer) -> TuiClientContext:
    return TuiClientContext(
        client=AgentClient(local_server.server_url),
        connection_info=ConnectionInfo(mode="local-server", server_url=local_server.server_url),
        local_server=local_server,
    )


def _start_local_server(
    *,
    project_root: Path,
    agent_specs: list[str] | None,
    default_agent: str | None,
) -> TuiClientContext:
    local_server = _spawn_local_server(
        project_root=project_root,
        agent_specs=agent_specs,
        default_agent=default_agent,
    )
    return _build_local_server_context(local_server)


def _ensure_server_healthy(server_url: str) -> None:
    if _server_healthy(server_url):
        return
    print(
        f"Server not reachable at {server_url}. Start it with `lattice server`.",
        file=sys.stderr,
    )
    raise SystemExit(1)

from __future__ import annotations

import asyncio
import argparse
import logging
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

from lattis.agents.registry import load_registry
from lattis.client import AgentClient
from lattis.runtime.context import AppContext
from lattis.scheduler import SchedulerConfig, run_scheduler
from lattis.settings.env import (
    AGENT_DEFAULT,
    AGENT_PLUGINS,
    LATTIS_PROJECT_ROOT,
    LATTIS_SERVER_URL,
    LATTIS_TELEGRAM_BOT_TOKEN,
    LATTIS_TELEGRAM_SESSION_ID,
    LATTIS_TELEGRAM_THREAD_PREFIX,
    read_env,
)
from lattis.settings.storage import load_storage_config
from lattis.storage.sqlite import SQLiteSessionStore
from lattis.telegram import (
    DEFAULT_TELEGRAM_SESSION_ID,
    DEFAULT_TELEGRAM_THREAD_PREFIX,
    TelegramBotConfig,
    run_telegram_bridge,
)
from lattis.tui.app import run_tui

DEFAULT_SERVER_URL = read_env(LATTIS_SERVER_URL)
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
    if command == "telegram":
        _run_telegram_command(args)
        return
    if command == "scheduler":
        _run_scheduler_command(args)
        return

    parser.print_help()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lattis", description="Agent CLI")
    subparsers = parser.add_subparsers(dest="command")

    tui_parser = subparsers.add_parser("tui", help="Run the TUI client")
    _add_tui_args(tui_parser)

    server_parser = subparsers.add_parser("server", help="Run the API server")
    _add_server_args(server_parser)

    telegram_parser = subparsers.add_parser("telegram", help="Run a Telegram chat bridge")
    _add_telegram_args(telegram_parser)

    scheduler_parser = subparsers.add_parser("scheduler", help="Run scheduled reminder worker")
    _add_scheduler_args(scheduler_parser)

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
        "--agent",
        default=None,
        help="Default agent id or name",
    )
    parser.add_argument(
        "--agents",
        default=None,
        help="Comma-separated agent plugin specs to load",
    )


def _add_telegram_args(parser: argparse.ArgumentParser) -> None:
    _add_tui_args(parser)
    parser.add_argument(
        "--token",
        default=read_env(LATTIS_TELEGRAM_BOT_TOKEN),
        help=f"Telegram bot token (or {LATTIS_TELEGRAM_BOT_TOKEN})",
    )
    parser.add_argument(
        "--session-id",
        default=read_env(LATTIS_TELEGRAM_SESSION_ID) or DEFAULT_TELEGRAM_SESSION_ID,
        help=f"Lattis session id for Telegram threads (or {LATTIS_TELEGRAM_SESSION_ID})",
    )
    parser.add_argument(
        "--thread-prefix",
        default=read_env(LATTIS_TELEGRAM_THREAD_PREFIX) or DEFAULT_TELEGRAM_THREAD_PREFIX,
        help=f"Thread id prefix per chat id (or {LATTIS_TELEGRAM_THREAD_PREFIX})",
    )
    parser.add_argument(
        "--poll-timeout",
        type=int,
        default=30,
        help="Telegram long-poll timeout in seconds (default: %(default)s)",
    )


def _add_scheduler_args(parser: argparse.ArgumentParser) -> None:
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
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Scheduler poll interval in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--claim-limit",
        type=int,
        default=10,
        help="Maximum due schedules claimed per loop (default: %(default)s)",
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=120,
        help="Lease time for claimed schedules (default: %(default)s)",
    )
    parser.add_argument(
        "--retry-seconds",
        type=int,
        default=60,
        help="Retry delay after failures (default: %(default)s)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scheduling pass and exit",
    )
    parser.add_argument(
        "--telegram-token",
        default=read_env(LATTIS_TELEGRAM_BOT_TOKEN),
        help=f"Telegram bot token for proactive delivery (or {LATTIS_TELEGRAM_BOT_TOKEN})",
    )
    parser.add_argument(
        "--telegram-thread-prefix",
        default=read_env(LATTIS_TELEGRAM_THREAD_PREFIX) or DEFAULT_TELEGRAM_THREAD_PREFIX,
        help=f"Thread id prefix used for Telegram mapping (or {LATTIS_TELEGRAM_THREAD_PREFIX})",
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
        default_agent=getattr(args, "agent", None),
        agent_specs=agent_specs,
    )

    uvicorn.run("lattis.server.asgi:app", host=args.host, port=args.port, reload=args.reload)


def _run_telegram_command(args: argparse.Namespace) -> None:
    token = str(getattr(args, "token", "") or "").strip()
    if not token:
        raise SystemExit(
            f"Missing Telegram bot token. Set --token or {LATTIS_TELEGRAM_BOT_TOKEN}."
        )

    session_id = str(getattr(args, "session_id", "") or "").strip() or DEFAULT_TELEGRAM_SESSION_ID
    thread_prefix = str(getattr(args, "thread_prefix", "") or "").strip() or DEFAULT_TELEGRAM_THREAD_PREFIX
    poll_timeout = max(int(getattr(args, "poll_timeout", 30) or 30), 1)

    project_root = Path.cwd()
    context = _create_tui_client(args, project_root=project_root)
    print(context.connection_info.status_message)
    print(
        "Telegram bridge ready:"
        f" session='{session_id}'"
        f" thread-prefix='{thread_prefix}'"
        " (send Ctrl+C to stop)."
    )

    config = TelegramBotConfig(
        token=token,
        session_id=session_id,
        thread_prefix=thread_prefix,
        poll_timeout=poll_timeout,
    )

    try:
        asyncio.run(run_telegram_bridge(client=context.client, config=config))
    except KeyboardInterrupt:
        pass
    finally:
        asyncio.run(context.client.close())
        if context.local_server:
            context.local_server.shutdown()


def _run_scheduler_command(args: argparse.Namespace) -> None:
    project_root = Path.cwd()
    agent_specs = _parse_agent_specs(getattr(args, "agents", None))
    _apply_server_env_defaults(
        project_root=project_root,
        default_agent=getattr(args, "agent", None),
        agent_specs=agent_specs,
    )

    config = load_storage_config(project_root=project_root)
    registry = load_registry(plugin_specs=agent_specs, default_spec=getattr(args, "agent", None))
    store = SQLiteSessionStore(config.db_path)
    ctx = AppContext(config=config, store=store, registry=registry)

    scheduler_config = SchedulerConfig(
        poll_interval_seconds=max(0.1, float(getattr(args, "poll_interval", 2.0) or 2.0)),
        claim_limit=max(1, int(getattr(args, "claim_limit", 10) or 10)),
        lease_seconds=max(1, int(getattr(args, "lease_seconds", 120) or 120)),
        retry_delay_seconds=max(1, int(getattr(args, "retry_seconds", 60) or 60)),
        run_once=bool(getattr(args, "once", False)),
        telegram_bot_token=str(getattr(args, "telegram_token", "") or "").strip() or None,
        telegram_thread_prefix=str(
            getattr(args, "telegram_thread_prefix", "") or DEFAULT_TELEGRAM_THREAD_PREFIX
        ).strip()
        or DEFAULT_TELEGRAM_THREAD_PREFIX,
    )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    asyncio.run(run_scheduler(ctx, scheduler_config))


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
        default_agent=default_agent,
        agent_specs=agent_specs,
    )

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "lattis.server.asgi:app",
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
            raise SystemExit("Local server failed to start (timeout). Try `lattis server` for logs.")
        raise SystemExit(
            f"Local server failed to start (exit code {exit_code}). Try `lattis server` for logs."
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


def _create_tui_client(args: argparse.Namespace, *, project_root: Path) -> TuiClientContext:
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
    default_agent: str | None,
    agent_specs: list[str] | None,
) -> None:
    _populate_server_env(
        os.environ,
        project_root=project_root,
        default_agent=default_agent,
        agent_specs=agent_specs,
        use_defaults=True,
    )


def _build_server_env(
    *,
    project_root: Path,
    default_agent: str | None,
    agent_specs: list[str] | None,
) -> dict[str, str]:
    env = os.environ.copy()
    _populate_server_env(
        env,
        project_root=project_root,
        default_agent=default_agent,
        agent_specs=agent_specs,
        use_defaults=False,
    )
    return env


def _populate_server_env(
    env: dict[str, str],
    *,
    project_root: Path,
    default_agent: str | None,
    agent_specs: list[str] | None,
    use_defaults: bool,
) -> None:
    def set_value(key: str, value: str) -> None:
        if use_defaults:
            env.setdefault(key, value)
        else:
            env[key] = value

    set_value(LATTIS_PROJECT_ROOT, str(project_root))
    if default_agent is not None:
        set_value(AGENT_DEFAULT, str(default_agent))
    if agent_specs is not None:
        set_value(AGENT_PLUGINS, ",".join(agent_specs))


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
        f"Server not reachable at {server_url}. Start it with `lattis server`.",
        file=sys.stderr,
    )
    raise SystemExit(1)

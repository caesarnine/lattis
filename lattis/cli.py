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

from lattis.client import AgentClient
from lattis.server.app import create_app
from lattis.server.routers.meta import get_lattis_version
from lattis.settings.env import (
    AGENT_DEFAULT,
    AGENT_PLUGINS,
    LATTIS_API_TOKEN,
    LATTIS_CORS_ORIGINS,
    LATTIS_NO_AUTH,
    LATTIS_SERVER_URL,
    read_env,
)
from lattis.settings.storage import (
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
    DaemonConfig,
    DaemonInfo,
    load_daemon_config,
    load_or_create_auth_token,
    read_daemon_info,
    remove_daemon_info,
    write_daemon_info,
)
from lattis.tui.app import run_tui


@dataclass
class ConnectionInfo:
    """Information about the TUI's daemon connection."""

    mode: str  # "remote" or "daemon"
    server_url: str

    @property
    def status_message(self) -> str:
        if self.mode == "remote":
            return f"Connecting to {self.server_url}..."
        return f"Connected to Lattis daemon at {self.server_url}"

    @property
    def header_label(self) -> str:
        parsed = urlparse(self.server_url)
        if self.mode == "remote":
            return parsed.netloc or self.server_url
        return f"daemon:{parsed.port}" if parsed.port else "daemon"


@dataclass
class TuiClientContext:
    client: AgentClient
    connection_info: ConnectionInfo
    project_root: Path | None
    default_agent: str | None = None


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
    if command in {"daemon", "server"}:
        _run_daemon_command(args)
        return

    parser.print_help()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lattis", description="Lattis agent daemon & CLI")
    subparsers = parser.add_subparsers(dest="command")

    tui_parser = subparsers.add_parser("tui", help="Attach the TUI client to the Lattis daemon")
    _add_tui_args(tui_parser)

    daemon_parser = subparsers.add_parser("daemon", help="Run the always-on Lattis daemon")
    _add_daemon_args(daemon_parser)

    server_parser = subparsers.add_parser("server", help="Alias for `lattis daemon`")
    _add_daemon_args(server_parser)

    return parser


def _add_tui_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--server",
        default=read_env(LATTIS_SERVER_URL),
        help="Connect to a remote Lattis daemon URL",
    )
    parser.add_argument(
        "--token",
        default=read_env(LATTIS_API_TOKEN),
        help="Bearer token for authentication",
    )
    parser.add_argument(
        "--global",
        dest="use_global",
        action="store_true",
        help="Attach to the built-in global workspace instead of current directory",
    )
    parser.add_argument(
        "--agent",
        default=None,
        help="Default agent id or name for newly started daemon / threads",
    )
    parser.add_argument(
        "--agents",
        default=None,
        help="Comma-separated agent plugin specs to load when auto-starting daemon",
    )


def _add_daemon_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        default=DEFAULT_DAEMON_HOST,
        help="Host interface to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DAEMON_PORT,
        help="Port to bind (default: %(default)s)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload",
    )
    parser.add_argument(
        "--cors",
        default=None,
        help="Comma-separated allowed CORS origins (default: none / same-origin)",
    )
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable bearer token authentication (dev only)",
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


def _pick_daemon_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, DEFAULT_DAEMON_PORT))
        except OSError:
            pass
        else:
            return DEFAULT_DAEMON_PORT

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def _wait_for_server(server_url: str, process: subprocess.Popen, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if _server_healthy(server_url):
            return True
        time.sleep(0.1)
    return False


def _ensure_local_daemon(
    config: DaemonConfig,
    *,
    default_agent: str | None,
    agent_specs: str | None,
) -> tuple[str, str | None]:
    # 1. Reuse existing daemon from daemon.json if healthy
    existing = read_daemon_info(config.daemon_info_path)
    if existing and _server_healthy(existing.api_url):
        token = load_or_create_auth_token(config)
        return existing.api_url, token

    # 2. Probe default daemon port in case daemon.json wasn't written yet
    default_url = f"http://{DEFAULT_DAEMON_HOST}:{DEFAULT_DAEMON_PORT}"
    if _server_healthy(default_url):
        token = load_or_create_auth_token(config)
        return default_url, token

    # 3. Spawn a detached background daemon process
    port = _pick_daemon_port(DEFAULT_DAEMON_HOST)
    api_url = f"http://{DEFAULT_DAEMON_HOST}:{port}"
    token = load_or_create_auth_token(config)

    env = os.environ.copy()
    if default_agent:
        env[AGENT_DEFAULT] = default_agent
    if agent_specs:
        env[AGENT_PLUGINS] = agent_specs

    cmd = [
        sys.executable,
        "-m",
        "lattis",
        "daemon",
        "--host",
        DEFAULT_DAEMON_HOST,
        "--port",
        str(port),
    ]
    process = subprocess.Popen(
        cmd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if not _wait_for_server(api_url, process):
        exit_code = process.poll()
        raise SystemExit(
            f"Failed to start Lattis daemon (exit={exit_code}). Try `lattis daemon` for logs."
        )
    return api_url, token


def _run_daemon_command(args: argparse.Namespace) -> None:
    if args.agent:
        os.environ[AGENT_DEFAULT] = args.agent
    if args.agents:
        os.environ[AGENT_PLUGINS] = args.agents
    if args.cors is not None:
        os.environ[LATTIS_CORS_ORIGINS] = args.cors
    if args.no_auth:
        os.environ[LATTIS_NO_AUTH] = "1"

    config = load_daemon_config(auth_disabled=bool(args.no_auth) or None)
    token = load_or_create_auth_token(config)
    api_url = f"http://{args.host}:{args.port}"
    info = DaemonInfo(
        pid=os.getpid(),
        host=args.host,
        port=args.port,
        api_url=api_url,
        version=get_lattis_version(),
        started_at=time.time(),
    )
    write_daemon_info(config.daemon_info_path, info)
    print(f"Lattis daemon listening on {api_url} (home: {config.home_dir})")
    if token is None:
        print("Auth: disabled")
    else:
        print(f"Auth: enabled (token stored in {config.token_path})")

    try:
        if args.reload:
            uvicorn.run("lattis.server.asgi:app", host=args.host, port=args.port, reload=True)
        else:
            app = create_app(config=config, auth_token=token)
            uv_config = uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                timeout_graceful_shutdown=3,
            )

            class _DaemonServer(uvicorn.Server):
                def handle_exit(self, sig, frame) -> None:
                    try:
                        app.state.ctx.bus.close()
                    except Exception:
                        pass
                    super().handle_exit(sig, frame)

                async def shutdown(self, sockets=None) -> None:
                    try:
                        await super().shutdown(sockets=sockets)
                    finally:
                        remove_daemon_info(config.daemon_info_path, pid=os.getpid())

            _DaemonServer(uv_config).run()
    finally:
        remove_daemon_info(config.daemon_info_path, pid=os.getpid())


def _run_tui_command(args: argparse.Namespace) -> None:
    config = load_daemon_config()
    if args.server:
        server_url = _normalize_server_url(args.server)
        if not _server_healthy(server_url):
            print(f"Lattis daemon not reachable at {server_url}.", file=sys.stderr)
            raise SystemExit(1)
        token = args.token or load_or_create_auth_token(config)
        conn_info = ConnectionInfo(mode="remote", server_url=server_url)
    else:
        server_url, token = _ensure_local_daemon(
            config,
            default_agent=args.agent,
            agent_specs=args.agents,
        )
        if args.token:
            token = args.token
        conn_info = ConnectionInfo(mode="daemon", server_url=server_url)

    project_root = None if args.use_global else Path.cwd()
    client = AgentClient(server_url, token=token)
    print(conn_info.status_message)
    run_tui(
        client=client,
        connection_info=conn_info,
        project_root=project_root,
        default_agent=args.agent or read_env(AGENT_DEFAULT),
    )

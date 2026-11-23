from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lattis.settings.env import (
    LATTIS_API_TOKEN,
    LATTIS_CORS_ORIGINS,
    LATTIS_HOME,
    LATTIS_NO_AUTH,
    read_bool_env,
    read_csv_env,
    read_env,
)

DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 7700


@dataclass(frozen=True)
class DaemonConfig:
    home_dir: Path
    db_path: Path
    daemon_info_path: Path
    token_path: Path
    plugins_dir: Path
    workspaces_dir: Path
    global_workspace_dir: Path
    cors_origins: tuple[str, ...] = ()
    auth_disabled: bool = False

    def plugin_data_dir(self, agent_id: str) -> Path:
        path = self.plugins_dir / _safe_segment(agent_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def workspace_data_dir(self, workspace_id: str, agent_id: str) -> Path:
        path = self.workspaces_dir / _safe_segment(workspace_id) / "plugins" / _safe_segment(agent_id)
        path.mkdir(parents=True, exist_ok=True)
        return path


@dataclass(frozen=True)
class DaemonInfo:
    pid: int
    host: str
    port: int
    api_url: str
    version: str
    started_at: float


def _safe_segment(value: str) -> str:
    cleaned = "".join(ch if (ch.isalnum() or ch in {"-", "_", "."}) else "_" for ch in value.strip())
    return cleaned.strip(".") or "default"


def _coerce_path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def resolve_daemon_config(
    *,
    home_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    cors_origins: tuple[str, ...] | list[str] | None = None,
    auth_disabled: bool | None = None,
) -> DaemonConfig:
    if home_dir is not None:
        resolved_home = _coerce_path(home_dir)
    else:
        env_home = read_env(LATTIS_HOME)
        resolved_home = _coerce_path(env_home) if env_home else _coerce_path(Path.home() / ".lattis")

    resolved_db = _coerce_path(db_path) if db_path is not None else resolved_home / "lattis.db"
    resolved_cors = (
        tuple(cors_origins) if cors_origins is not None else tuple(read_csv_env(LATTIS_CORS_ORIGINS))
    )
    resolved_no_auth = (
        auth_disabled if auth_disabled is not None else read_bool_env(LATTIS_NO_AUTH, default=False)
    )

    workspaces_dir = resolved_home / "workspaces"
    return DaemonConfig(
        home_dir=resolved_home,
        db_path=resolved_db,
        daemon_info_path=resolved_home / "daemon.json",
        token_path=resolved_home / "auth.token",
        plugins_dir=resolved_home / "plugins",
        workspaces_dir=workspaces_dir,
        global_workspace_dir=workspaces_dir / "global",
        cors_origins=resolved_cors,
        auth_disabled=resolved_no_auth,
    )


def ensure_daemon_dirs(config: DaemonConfig) -> None:
    config.home_dir.mkdir(parents=True, exist_ok=True)
    config.plugins_dir.mkdir(parents=True, exist_ok=True)
    config.workspaces_dir.mkdir(parents=True, exist_ok=True)
    config.global_workspace_dir.mkdir(parents=True, exist_ok=True)


def load_daemon_config(
    *,
    home_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    cors_origins: tuple[str, ...] | list[str] | None = None,
    auth_disabled: bool | None = None,
) -> DaemonConfig:
    config = resolve_daemon_config(
        home_dir=home_dir,
        db_path=db_path,
        cors_origins=cors_origins,
        auth_disabled=auth_disabled,
    )
    ensure_daemon_dirs(config)
    return config


def load_or_create_auth_token(config: DaemonConfig, *, explicit_token: str | None = None) -> str | None:
    if config.auth_disabled:
        return None
    if explicit_token is not None:
        token = explicit_token.strip()
        return token or None
    env_token = read_env(LATTIS_API_TOKEN)
    if env_token:
        return env_token
    if config.token_path.exists():
        existing = config.token_path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    token = secrets.token_hex(32)
    config.token_path.parent.mkdir(parents=True, exist_ok=True)
    config.token_path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(config.token_path, 0o600)
    except OSError:
        pass
    return token


def write_daemon_info(path: Path, info: DaemonInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "pid": info.pid,
        "host": info.host,
        "port": info.port,
        "api_url": info.api_url,
        "version": info.version,
        "started_at": info.started_at,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_daemon_info(path: Path) -> DaemonInfo | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        return DaemonInfo(
            pid=int(raw["pid"]),
            host=str(raw["host"]),
            port=int(raw["port"]),
            api_url=str(raw["api_url"]),
            version=str(raw.get("version", "unknown")),
            started_at=float(raw.get("started_at", 0.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def remove_daemon_info(path: Path, *, pid: int | None = None) -> None:
    if pid is not None:
        current = read_daemon_info(path)
        if current is not None and current.pid != pid:
            return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lattis.settings.env import (
    LATTIS_DATA_DIR,
    LATTIS_DATA_DIR_NAME,
    LATTIS_DB_PATH,
    LATTIS_PROJECT_ROOT,
    LATTIS_SESSION_FILE,
    LATTIS_SESSION_ID,
    LATTIS_WORKSPACE_DIR,
    LATTIS_WORKSPACE_MODE,
    read_env,
)


@dataclass(frozen=True)
class StorageConfig:
    data_dir: Path
    db_path: Path
    session_id_path: Path
    workspace_dir: Path
    project_root: Path
    workspace_mode: Literal["central", "local"]


def _coerce_path(value: Path | str) -> Path:
    return Path(value).expanduser()


def _resolve_workspace_mode(value: str | None) -> Literal["central", "local"]:
    value = (value or "local").strip().lower()
    if value in {"local", "project", "cwd"}:
        return "local"
    return "central"


def _normalize_data_dir_name(value: str | None) -> str:
    if value is None:
        return "lattis"
    value = value.strip().lstrip(".")
    if not value:
        return "lattis"
    for sep in (os.sep, os.altsep):
        if sep and sep in value:
            return "lattis"
    return value


def resolve_storage_config(
    *,
    project_root: Path | str | None = None,
    workspace_mode: str | None = None,
    data_dir_name: str | None = None,
    data_dir: Path | str | None = None,
    workspace_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    session_id_path: Path | str | None = None,
) -> StorageConfig:
    if project_root is not None:
        resolved_project_root = _coerce_path(project_root)
    else:
        resolved_project_root = Path.cwd()
    resolved_mode = _resolve_workspace_mode(workspace_mode)

    if data_dir is None:
        dir_name = f".{_normalize_data_dir_name(data_dir_name)}"
        if resolved_mode == "local":
            data_dir = resolved_project_root / dir_name
        else:
            data_dir = Path.home() / dir_name
    else:
        data_dir = _coerce_path(data_dir)

    if workspace_dir is None:
        workspace_dir = data_dir / "workspace"
    else:
        workspace_dir = _coerce_path(workspace_dir)

    db_path = _coerce_path(db_path) if db_path is not None else data_dir / "lattis.db"
    session_id_path = (
        _coerce_path(session_id_path) if session_id_path is not None else data_dir / "session_id"
    )

    return StorageConfig(
        data_dir=data_dir,
        db_path=db_path,
        session_id_path=session_id_path,
        workspace_dir=workspace_dir,
        project_root=resolved_project_root,
        workspace_mode=resolved_mode,
    )


def ensure_storage_dirs(config: StorageConfig) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.workspace_dir.mkdir(parents=True, exist_ok=True)


def resolve_storage_config_from_env(
    *,
    project_root: Path | str | None = None,
    workspace_mode: str | None = None,
    data_dir_name: str | None = None,
    data_dir: Path | str | None = None,
    workspace_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    session_id_path: Path | str | None = None,
) -> StorageConfig:
    env_project_root = read_env(LATTIS_PROJECT_ROOT)
    env_workspace_mode = read_env(LATTIS_WORKSPACE_MODE)
    env_data_dir_name = read_env(LATTIS_DATA_DIR_NAME)
    env_data_dir = read_env(LATTIS_DATA_DIR)
    env_workspace_dir = read_env(LATTIS_WORKSPACE_DIR)
    env_db_path = read_env(LATTIS_DB_PATH)
    env_session_path = read_env(LATTIS_SESSION_FILE)
    return resolve_storage_config(
        project_root=project_root or env_project_root,
        workspace_mode=workspace_mode or env_workspace_mode,
        data_dir_name=data_dir_name or env_data_dir_name,
        data_dir=data_dir or env_data_dir,
        workspace_dir=workspace_dir or env_workspace_dir,
        db_path=db_path or env_db_path,
        session_id_path=session_id_path or env_session_path,
    )


def load_storage_config(
    *,
    project_root: Path | str | None = None,
    workspace_mode: str | None = None,
    data_dir_name: str | None = None,
    data_dir: Path | str | None = None,
    workspace_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    session_id_path: Path | str | None = None,
) -> StorageConfig:
    config = resolve_storage_config_from_env(
        project_root=project_root,
        workspace_mode=workspace_mode,
        data_dir_name=data_dir_name,
        data_dir=data_dir,
        workspace_dir=workspace_dir,
        db_path=db_path,
        session_id_path=session_id_path,
    )
    ensure_storage_dirs(config)
    return config


def load_or_create_session_id(path: Path, *, env_var: str = LATTIS_SESSION_ID) -> str:
    override = read_env(env_var)
    if override:
        return override
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    session_id = f"tui-{uuid.uuid4()}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(session_id, encoding="utf-8")
    return session_id

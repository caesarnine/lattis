from __future__ import annotations

import os

LATTIS_SERVER_URL = "LATTIS_SERVER_URL"
LATTIS_WORKSPACE_MODE = "LATTIS_WORKSPACE_MODE"
LATTIS_PROJECT_ROOT = "LATTIS_PROJECT_ROOT"
LATTIS_DATA_DIR = "LATTIS_DATA_DIR"
LATTIS_DATA_DIR_NAME = "LATTIS_DATA_DIR_NAME"
LATTIS_WORKSPACE_DIR = "LATTIS_WORKSPACE_DIR"
LATTIS_DB_PATH = "LATTIS_DB_PATH"
LATTIS_SESSION_FILE = "LATTIS_SESSION_FILE"
LATTIS_SESSION_ID = "LATTIS_SESSION_ID"

AGENT_MODEL = "AGENT_MODEL"
AGENT_DEFAULT = "AGENT_DEFAULT"
AGENT_PLUGINS = "AGENT_PLUGINS"
AGENT_PLUGIN = "AGENT_PLUGIN"


def read_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def first_env(*names: str) -> str | None:
    for name in names:
        value = read_env(name)
        if value is not None:
            return value
    return None


def read_bool_env(name: str, *, default: bool = False) -> bool:
    value = read_env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}

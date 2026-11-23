from __future__ import annotations

import os

LATTIS_HOME = "LATTIS_HOME"
LATTIS_SERVER_URL = "LATTIS_SERVER_URL"
LATTIS_API_TOKEN = "LATTIS_API_TOKEN"
LATTIS_CORS_ORIGINS = "LATTIS_CORS_ORIGINS"
LATTIS_NO_AUTH = "LATTIS_NO_AUTH"

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


def read_csv_env(name: str) -> list[str]:
    value = read_env(name)
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]

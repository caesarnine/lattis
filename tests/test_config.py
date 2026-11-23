from __future__ import annotations

from pathlib import Path

from lattis.settings.storage import (
    DaemonInfo,
    load_daemon_config,
    load_or_create_auth_token,
    read_daemon_info,
    remove_daemon_info,
    resolve_daemon_config,
    write_daemon_info,
)


def test_resolve_daemon_config_is_pure(tmp_path: Path) -> None:
    home = tmp_path / "lattis_home"
    config = resolve_daemon_config(home_dir=home)

    assert config.home_dir == home.resolve(strict=False)
    assert config.db_path == home.resolve(strict=False) / "lattis.db"
    assert not home.exists()


def test_load_daemon_config_creates_dirs(tmp_path: Path) -> None:
    home = tmp_path / "lattis_home"
    config = load_daemon_config(home_dir=home)

    assert config.home_dir.is_dir()
    assert config.plugins_dir.is_dir()
    assert config.workspaces_dir.is_dir()
    assert config.global_workspace_dir.is_dir()


def test_load_or_create_auth_token_persists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("LATTIS_API_TOKEN", raising=False)
    config = load_daemon_config(home_dir=tmp_path / "home")
    token1 = load_or_create_auth_token(config)
    token2 = load_or_create_auth_token(config)

    assert token1 is not None
    assert len(token1) == 64
    assert token1 == token2
    assert config.token_path.exists()


def test_daemon_info_roundtrip_and_pid_guard(tmp_path: Path) -> None:
    info_path = tmp_path / "daemon.json"
    info = DaemonInfo(
        pid=12345,
        host="127.0.0.1",
        port=7700,
        api_url="http://127.0.0.1:7700",
        version="0.7.0",
        started_at=1000.0,
    )
    write_daemon_info(info_path, info)
    assert read_daemon_info(info_path) == info

    # Wrong PID should not remove file
    remove_daemon_info(info_path, pid=99999)
    assert info_path.exists()

    # Matching PID removes file
    remove_daemon_info(info_path, pid=12345)
    assert not info_path.exists()

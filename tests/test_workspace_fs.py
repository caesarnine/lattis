from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from lattis.client.inprocess import create_inprocess_client


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_workspace_files_read_and_path_jail(tmp_path: Path) -> None:
    async def _run() -> None:
        secret = tmp_path / "outside_secret.txt"
        secret.write_text("TOP SECRET", encoding="utf-8")

        proj = tmp_path / "project"
        (proj / "src").mkdir(parents=True)
        (proj / "node_modules").mkdir()
        (proj / ".hidden").write_text("hidden", encoding="utf-8")
        (proj / "README.md").write_text("Hello workspace!\n", encoding="utf-8")
        (proj / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
        (proj / "bin.dat").write_bytes(b"\x00\x01\x02binary")
        (proj / "escape_link").symlink_to(secret)

        client, daemon = create_inprocess_client(home_dir=tmp_path / "home")
        try:
            ws = await client.register_workspace(str(proj))

            # Root listing: dirs first, skips hidden & node_modules & escaping symlink
            listing = await client.list_workspace_files(ws.id)
            names = [e.name for e in listing.entries]
            assert names == ["src", "bin.dat", "README.md"]
            assert listing.entries[0].kind == "dir"

            # Subdir listing
            sub = await client.list_workspace_files(ws.id, path="src")
            assert [e.path for e in sub.entries] == ["src/main.py"]

            # Text file read + truncation
            readme = await client.read_workspace_file(ws.id, "README.md")
            assert readme.content == "Hello workspace!\n"
            assert readme.is_binary is False
            assert readme.truncated is False

            short = await client.read_workspace_file(ws.id, "README.md", max_bytes=5)
            assert short.content == "Hello"
            assert short.truncated is True

            # Binary detection
            binary = await client.read_workspace_file(ws.id, "bin.dat")
            assert binary.is_binary is True
            assert binary.content == ""

            # Path traversal & symlink escape blocked
            for bad_path in ("../outside_secret.txt", "/etc/passwd", "escape_link"):
                try:
                    await client.read_workspace_file(ws.id, bad_path)
                    assert False, f"Expected path jail rejection for {bad_path}"
                except RuntimeError as exc:
                    assert "escapes" in str(exc) or "Absolute" in str(exc)
        finally:
            await client.close()
            await daemon.aclose()

    asyncio.run(_run())


def test_workspace_git_status_and_diff(tmp_path: Path) -> None:
    async def _run() -> None:
        non_git = tmp_path / "plain_dir"
        non_git.mkdir()

        repo = tmp_path / "git_repo"
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Tester")

        tracked = repo / "app.py"
        tracked.write_text("line1\nline2\n", encoding="utf-8")
        _git(repo, "add", "app.py")
        _git(repo, "commit", "-m", "initial")

        # Modify tracked file, stage another file, and create an untracked file
        tracked.write_text("line1\nline2-edited\n", encoding="utf-8")
        staged_file = repo / "staged.txt"
        staged_file.write_text("hello staged\n", encoding="utf-8")
        _git(repo, "add", "staged.txt")
        untracked_file = repo / "notes.md"
        untracked_file.write_text("# New notes\nline two\n", encoding="utf-8")

        client, daemon = create_inprocess_client(home_dir=tmp_path / "home")
        try:
            ws_plain = await client.register_workspace(str(non_git))
            plain_status = await client.get_git_status(ws_plain.id)
            assert plain_status.is_git_repo is False
            assert plain_status.files == []

            ws_repo = await client.register_workspace(str(repo))
            status = await client.get_git_status(ws_repo.id)
            assert status.is_git_repo is True
            assert status.branch == "main"
            by_path = {f.path: f.status for f in status.files}
            assert by_path == {
                "app.py": "modified",
                "staged.txt": "added",
                "notes.md": "untracked",
            }

            # Unstaged diff on modified file
            diff_mod = await client.get_git_diff(ws_repo.id, path="app.py")
            assert "-line2" in diff_mod.diff
            assert "+line2-edited" in diff_mod.diff

            # Staged diff
            diff_staged = await client.get_git_diff(ws_repo.id, path="staged.txt", staged=True)
            assert "+hello staged" in diff_staged.diff

            # Synthetic unified diff for untracked file
            diff_untracked = await client.get_git_diff(ws_repo.id, path="notes.md")
            assert "--- /dev/null" in diff_untracked.diff
            assert "+# New notes" in diff_untracked.diff
        finally:
            await client.close()
            await daemon.aclose()

    asyncio.run(_run())

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

DEFAULT_IGNORED_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
    }
)

DEFAULT_MAX_FILE_BYTES = 262_144  # 256 KB
DEFAULT_MAX_DIFF_CHARS = 200_000


class WorkspacePathError(ValueError):
    """Raised when a requested path escapes the workspace root or is invalid."""


@dataclass(frozen=True)
class FileEntryData:
    name: str
    path: str
    kind: Literal["dir", "file"]
    size: int | None = None
    mtime: float | None = None


@dataclass(frozen=True)
class FileReadData:
    path: str
    content: str
    size: int
    is_binary: bool
    truncated: bool


@dataclass(frozen=True)
class GitFileStatusData:
    path: str
    index_status: str
    worktree_status: str
    status: Literal["modified", "added", "deleted", "renamed", "untracked", "conflicted"]


@dataclass(frozen=True)
class GitStatusData:
    is_git_repo: bool
    branch: str | None
    ahead: int
    behind: int
    files: list[GitFileStatusData]


@dataclass(frozen=True)
class GitDiffData:
    is_git_repo: bool
    path: str | None
    staged: bool
    diff: str
    truncated: bool


def resolve_workspace_path(root: Path, rel_path: str = "") -> Path:
    """Resolve `rel_path` strictly inside `root`, blocking traversal and symlink escapes."""
    root_resolved = root.expanduser().resolve(strict=False)
    cleaned = (rel_path or "").strip()
    if not cleaned or cleaned in {".", "./"}:
        return root_resolved

    candidate_rel = Path(cleaned)
    if candidate_rel.is_absolute():
        raise WorkspacePathError("Absolute paths are not allowed; provide a workspace-relative path.")

    joined = (root_resolved / candidate_rel).resolve(strict=False)
    try:
        joined.relative_to(root_resolved)
    except ValueError as exc:
        raise WorkspacePathError(f"Path '{rel_path}' escapes workspace root.") from exc
    return joined


def list_workspace_files(
    root: Path,
    *,
    rel_path: str = "",
    include_hidden: bool = False,
    limit: int = 500,
) -> tuple[str, list[FileEntryData]]:
    root_resolved = root.expanduser().resolve(strict=False)
    target = resolve_workspace_path(root_resolved, rel_path)
    if not target.exists():
        raise FileNotFoundError(f"Path '{rel_path or '.'}' does not exist.")
    if not target.is_dir():
        raise WorkspacePathError(f"Path '{rel_path}' is not a directory.")

    entries: list[FileEntryData] = []
    try:
        children = list(target.iterdir())
    except OSError as exc:
        raise WorkspacePathError(f"Unable to list directory: {exc}") from exc

    for child in children:
        name = child.name
        if not include_hidden and name.startswith("."):
            continue
        if child.is_dir() and name in DEFAULT_IGNORED_DIRS and not rel_path:
            continue
        try:
            resolved_child = child.resolve(strict=False)
            resolved_child.relative_to(root_resolved)
        except (OSError, ValueError):
            # Skip symlinks pointing outside workspace root
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        is_dir = child.is_dir()
        rel = str(child.relative_to(root_resolved)).replace("\\", "/")
        entries.append(
            FileEntryData(
                name=name,
                path=rel,
                kind="dir" if is_dir else "file",
                size=None if is_dir else int(stat.st_size),
                mtime=float(stat.st_mtime),
            )
        )

    entries.sort(key=lambda e: (0 if e.kind == "dir" else 1, e.name.casefold()))
    normalized_rel = "" if target == root_resolved else str(target.relative_to(root_resolved)).replace("\\", "/")
    return normalized_rel, entries[:limit]


def read_workspace_file(
    root: Path,
    *,
    rel_path: str,
    max_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> FileReadData:
    if not rel_path.strip():
        raise WorkspacePathError("File path is required.")
    root_resolved = root.expanduser().resolve(strict=False)
    target = resolve_workspace_path(root_resolved, rel_path)
    if not target.exists():
        raise FileNotFoundError(f"File '{rel_path}' does not exist.")
    if not target.is_file():
        raise WorkspacePathError(f"Path '{rel_path}' is not a file.")

    size = int(target.stat().st_size)
    with target.open("rb") as fh:
        raw = fh.read(max_bytes + 1)

    truncated = len(raw) > max_bytes
    if truncated:
        raw = raw[:max_bytes]

    # Simple binary heuristic: NUL byte in sample
    if b"\x00" in raw[:8192]:
        return FileReadData(
            path=str(target.relative_to(root_resolved)).replace("\\", "/"),
            content="",
            size=size,
            is_binary=True,
            truncated=truncated,
        )

    text = raw.decode("utf-8", errors="replace")
    return FileReadData(
        path=str(target.relative_to(root_resolved)).replace("\\", "/"),
        content=text,
        size=size,
        is_binary=False,
        truncated=truncated,
    )


async def _run_git(cwd: Path, args: list[str], *, timeout: float = 10.0) -> tuple[int, str, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return 127, "", "git executable not found"

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "git command timed out"

    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


def _classify_git_status(index_code: str, worktree_code: str) -> Literal[
    "modified", "added", "deleted", "renamed", "untracked", "conflicted"
]:
    pair = index_code + worktree_code
    if pair == "??":
        return "untracked"
    if "U" in pair or pair in {"AA", "DD"}:
        return "conflicted"
    if "R" in pair or "C" in pair:
        return "renamed"
    if "D" in pair:
        return "deleted"
    if "A" in pair:
        return "added"
    return "modified"


def _parse_branch_header(header: str) -> tuple[str | None, int, int]:
    # Examples:
    #   "## main...origin/main [ahead 2, behind 1]"
    #   "## No commits yet on main"
    #   "## HEAD (no branch)"
    body = header[3:].strip()
    ahead = 0
    behind = 0

    if "[" in body and body.endswith("]"):
        bracket_start = body.rfind("[")
        meta = body[bracket_start + 1 : -1]
        body = body[:bracket_start].strip()
        for part in meta.split(","):
            tokens = part.strip().split()
            if len(tokens) == 2 and tokens[1].isdigit():
                if tokens[0] == "ahead":
                    ahead = int(tokens[1])
                elif tokens[0] == "behind":
                    behind = int(tokens[1])

    if body.startswith("No commits yet on "):
        branch = body.removeprefix("No commits yet on ").strip()
    elif "..." in body:
        branch = body.split("...", 1)[0].strip()
    else:
        branch = body or None
    return branch, ahead, behind


async def get_git_status(root: Path) -> GitStatusData:
    root_resolved = root.expanduser().resolve(strict=False)
    if not root_resolved.exists():
        return GitStatusData(is_git_repo=False, branch=None, ahead=0, behind=0, files=[])

    rc, out, _ = await _run_git(root_resolved, ["rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out.strip() != "true":
        return GitStatusData(is_git_repo=False, branch=None, ahead=0, behind=0, files=[])

    rc, porcelain, _ = await _run_git(root_resolved, ["status", "--porcelain=v1", "-b", "-uall"])
    if rc != 0:
        return GitStatusData(is_git_repo=True, branch=None, ahead=0, behind=0, files=[])

    branch: str | None = None
    ahead = 0
    behind = 0
    files: list[GitFileStatusData] = []

    for line in porcelain.splitlines():
        if line.startswith("## "):
            branch, ahead, behind = _parse_branch_header(line)
            continue
        if len(line) < 4:
            continue
        idx_code = line[0]
        wt_code = line[1]
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", 1)[1].strip()
        if raw_path.startswith('"') and raw_path.endswith('"'):
            raw_path = raw_path[1:-1]
        files.append(
            GitFileStatusData(
                path=raw_path,
                index_status=idx_code,
                worktree_status=wt_code,
                status=_classify_git_status(idx_code, wt_code),
            )
        )

    return GitStatusData(
        is_git_repo=True,
        branch=branch,
        ahead=ahead,
        behind=behind,
        files=files,
    )


def _format_untracked_diff(root: Path, rel_path: str, *, max_chars: int) -> tuple[str, bool]:
    try:
        read_res = read_workspace_file(root, rel_path=rel_path, max_bytes=max_chars)
    except (FileNotFoundError, WorkspacePathError, OSError):
        return "", False
    if read_res.is_binary:
        return f"Binary file {read_res.path} (untracked, {read_res.size} bytes)\n", False
    lines = read_res.content.splitlines()
    header = [
        f"diff --git a/{read_res.path} b/{read_res.path}",
        "new file mode 100644",
        "--- /dev/null",
        f"+++ b/{read_res.path}",
        f"@@ -0,0 +1,{len(lines)} @@",
    ]
    body = [f"+{line}" for line in lines]
    combined = "\n".join(header + body) + ("\n" if lines else "")
    if len(combined) > max_chars:
        return combined[:max_chars] + "\n... (diff truncated)\n", True
    return combined, read_res.truncated


async def get_git_diff(
    root: Path,
    *,
    rel_path: str | None = None,
    staged: bool = False,
    max_chars: int = DEFAULT_MAX_DIFF_CHARS,
) -> GitDiffData:
    root_resolved = root.expanduser().resolve(strict=False)
    if not root_resolved.exists():
        return GitDiffData(is_git_repo=False, path=rel_path, staged=staged, diff="", truncated=False)

    rc, out, _ = await _run_git(root_resolved, ["rev-parse", "--is-inside-work-tree"])
    if rc != 0 or out.strip() != "true":
        return GitDiffData(is_git_repo=False, path=rel_path, staged=staged, diff="", truncated=False)

    normalized_path: str | None = None
    if rel_path is not None and rel_path.strip():
        target = resolve_workspace_path(root_resolved, rel_path)
        normalized_path = str(target.relative_to(root_resolved)).replace("\\", "/")

    cmd = ["diff", "--no-color"]
    if staged:
        cmd.append("--cached")
    if normalized_path:
        cmd.extend(["--", normalized_path])

    rc, diff_text, _ = await _run_git(root_resolved, cmd)
    if rc != 0:
        return GitDiffData(is_git_repo=True, path=normalized_path, staged=staged, diff="", truncated=False)

    # If requesting a specific untracked file, synthesize a clean unified diff
    if not diff_text and normalized_path and not staged:
        untracked_rc, untracked_out, _ = await _run_git(
            root_resolved,
            ["ls-files", "--others", "--exclude-standard", "--", normalized_path],
        )
        if untracked_rc == 0 and untracked_out.strip():
            diff_text, truncated = _format_untracked_diff(
                root_resolved,
                normalized_path,
                max_chars=max_chars,
            )
            return GitDiffData(
                is_git_repo=True,
                path=normalized_path,
                staged=staged,
                diff=diff_text,
                truncated=truncated,
            )

    truncated = len(diff_text) > max_chars
    if truncated:
        diff_text = diff_text[:max_chars] + "\n... (diff truncated)\n"

    return GitDiffData(
        is_git_repo=True,
        path=normalized_path,
        staged=staged,
        diff=diff_text,
        truncated=truncated,
    )

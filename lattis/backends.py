from __future__ import annotations

import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai_backends import LocalBackend
from pydantic_ai_backends.protocol import BackendProtocol, SandboxProtocol
from pydantic_ai_backends.types import EditResult, ExecuteResponse, FileInfo, GrepMatch, WriteResult


def _is_root_path(path: str | None) -> bool:
    return path is None or not path.strip() or path.strip() == "/"


def _strip_project_prefix(path: str) -> str:
    stripped = path.strip()
    if stripped == "/project":
        return "."
    if stripped.startswith("/project/"):
        remainder = stripped[len("/project/") :]
        return remainder or "."
    if stripped.startswith("project/"):
        remainder = stripped[len("project/") :]
        return remainder or "."
    if stripped == "project":
        return "."
    return stripped


def _is_project_virtual_path(path: str | None) -> bool:
    if path is None:
        return False
    stripped = path.strip()
    return stripped == "/project" or stripped.startswith("/project/") or stripped == "project" or stripped.startswith(
        "project/"
    )


def _workspace_relative_path(path: str) -> str:
    stripped = path.strip()
    if stripped in {"", "/", "."}:
        return "."
    if stripped.startswith("/"):
        return stripped[1:] or "."
    return stripped


def _virtualize_path(*, host_path: str, root: Path, prefix: str) -> str:
    resolved_root = root.resolve()
    resolved_host = Path(host_path).resolve()
    rel = resolved_host.relative_to(resolved_root)
    rel_str = rel.as_posix()
    if rel_str == ".":
        return prefix.rstrip("/") or "/"
    if prefix.endswith("/"):
        return f"{prefix}{rel_str}"
    return f"{prefix}/{rel_str}"


@dataclass
class ProjectWorkspaceBackend(SandboxProtocol):
    """A path-routed backend that mounts a project and a per-thread workspace.

    Virtual paths:
    - `/project/...` → project root (read/write)
    - `/...` → workspace root (read/write)

    Shell execution runs with cwd set to the project root and PATH extended with
    `{workspace_root}/bin`.
    """

    project_root: Path
    workspace_root: Path

    def __post_init__(self) -> None:
        self.project_root = self.project_root.resolve()
        self.workspace_root = self.workspace_root.resolve()
        self._id = str(uuid.uuid4())
        self._project_token_re = re.compile(r'(?<![A-Za-z0-9_])(/project)(?=($|[\\s/\"\\\']))')

        self._workspace_backend: BackendProtocol = LocalBackend(root_dir=self.workspace_root)
        self._project_backend: BackendProtocol = LocalBackend(root_dir=self.project_root)

    @property
    def id(self) -> str:
        return self._id

    @property
    def execute_enabled(self) -> bool:
        return True

    def ls_info(self, path: str) -> list[FileInfo]:
        if _is_root_path(path):
            entries: list[FileInfo] = []

            entries.extend(self._virtualize_fileinfo_items(self._workspace_backend.ls_info(".")))

            # Ensure the project mount shows up at the top-level.
            if not any(item["name"] == "project" for item in entries):
                entries.append(
                    FileInfo(
                        name="project",
                        path="/project",
                        is_dir=True,
                        size=None,
                    )
                )
            return sorted(entries, key=lambda item: (not item["is_dir"], item["name"]))

        if _is_project_virtual_path(path):
            rel = _strip_project_prefix(path)
            return self._virtualize_fileinfo_items(
                self._project_backend.ls_info(rel),
                root=self.project_root,
                prefix="/project",
            )

        rel = _workspace_relative_path(path)
        return self._virtualize_fileinfo_items(self._workspace_backend.ls_info(rel))

    def _read_bytes(self, path: str) -> bytes:
        if _is_project_virtual_path(path):
            return self._project_backend._read_bytes(_strip_project_prefix(path))
        return self._workspace_backend._read_bytes(_workspace_relative_path(path))

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        if _is_project_virtual_path(path):
            return self._project_backend.read(_strip_project_prefix(path), offset, limit)
        return self._workspace_backend.read(_workspace_relative_path(path), offset, limit)

    def write(self, path: str, content: str | bytes) -> WriteResult:
        if _is_project_virtual_path(path):
            result = self._project_backend.write(_strip_project_prefix(path), content)
            return self._virtualize_write_result(result, root=self.project_root, prefix="/project")
        result = self._workspace_backend.write(_workspace_relative_path(path), content)
        return self._virtualize_write_result(result, root=self.workspace_root, prefix="")

    def edit(self, path: str, old_string: str, new_string: str, replace_all: bool = False) -> EditResult:
        if _is_project_virtual_path(path):
            result = self._project_backend.edit(
                _strip_project_prefix(path),
                old_string,
                new_string,
                replace_all,
            )
            return self._virtualize_edit_result(result, root=self.project_root, prefix="/project")

        result = self._workspace_backend.edit(
            _workspace_relative_path(path),
            old_string,
            new_string,
            replace_all,
        )
        return self._virtualize_edit_result(result, root=self.workspace_root, prefix="")

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        if _is_root_path(path):
            entries: list[FileInfo] = []
            entries.extend(self._virtualize_fileinfo_items(self._workspace_backend.glob_info(pattern, ".")))
            entries.extend(
                self._virtualize_fileinfo_items(
                    self._project_backend.glob_info(pattern, "."),
                    root=self.project_root,
                    prefix="/project",
                )
            )
            return sorted(entries, key=lambda item: item["path"])

        if _is_project_virtual_path(path):
            rel = _strip_project_prefix(path)
            return self._virtualize_fileinfo_items(
                self._project_backend.glob_info(pattern, rel),
                root=self.project_root,
                prefix="/project",
            )

        rel = _workspace_relative_path(path)
        return self._virtualize_fileinfo_items(self._workspace_backend.glob_info(pattern, rel))

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
        ignore_hidden: bool = True,
    ) -> list[GrepMatch] | str:
        if _is_root_path(path):
            matches: list[GrepMatch] = []
            workspace = self._workspace_backend.grep_raw(pattern, ".", glob, ignore_hidden)
            if isinstance(workspace, str):
                return workspace
            matches.extend(self._virtualize_grep_matches(workspace))

            project = self._project_backend.grep_raw(pattern, ".", glob, ignore_hidden)
            if isinstance(project, str):
                return project
            matches.extend(self._virtualize_grep_matches(project, root=self.project_root, prefix="/project"))
            return matches

        assert path is not None
        if _is_project_virtual_path(path):
            rel = _strip_project_prefix(path)
            result = self._project_backend.grep_raw(pattern, rel, glob, ignore_hidden)
            if isinstance(result, str):
                return result
            return self._virtualize_grep_matches(result, root=self.project_root, prefix="/project")

        rel = _workspace_relative_path(path)
        result = self._workspace_backend.grep_raw(pattern, rel, glob, ignore_hidden)
        if isinstance(result, str):
            return result
        return self._virtualize_grep_matches(result)

    def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        env = os.environ.copy()
        bin_path = str(self.workspace_root / "bin")
        tmp_path = str(self.workspace_root / "tmp")
        env["PATH"] = f"{bin_path}:{env.get('PATH', '')}"
        env["TMPDIR"] = tmp_path
        env["TEMP"] = tmp_path
        env["TMP"] = tmp_path
        env["LATTIS_PROJECT_ROOT"] = str(self.project_root)
        env["LATTIS_WORKSPACE_ROOT"] = str(self.workspace_root)

        rewritten_command = self._project_token_re.sub(str(self.project_root), command)

        try:
            result = subprocess.run(
                ["sh", "-c", rewritten_command],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout or 120,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ExecuteResponse(output="Error: Command timed out", exit_code=124, truncated=False)
        except Exception as exc:  # pragma: no cover
            return ExecuteResponse(output=f"Error: {exc}", exit_code=1, truncated=False)

        output = (result.stdout or "") + (result.stderr or "")
        max_output = 100000
        truncated = len(output) > max_output
        if truncated:  # pragma: no cover
            output = output[:max_output]

        return ExecuteResponse(output=output, exit_code=result.returncode, truncated=truncated)

    def _virtualize_fileinfo_items(
        self,
        items: list[FileInfo],
        *,
        root: Path | None = None,
        prefix: str = "",
    ) -> list[FileInfo]:
        root = root or self.workspace_root
        out: list[FileInfo] = []
        for item in items:
            try:
                virtual_path = _virtualize_path(host_path=item["path"], root=root, prefix=prefix or "/")
            except Exception:
                virtual_path = item["path"]
            out.append(
                FileInfo(
                    name=item["name"],
                    path=virtual_path,
                    is_dir=item["is_dir"],
                    size=item.get("size"),
                )
            )
        return out

    def _virtualize_write_result(self, result: WriteResult, *, root: Path, prefix: str) -> WriteResult:
        if result.error or not result.path:
            return WriteResult(error=result.error)
        try:
            virtual_path = _virtualize_path(host_path=result.path, root=root, prefix=prefix or "/")
        except Exception:
            virtual_path = result.path
        return WriteResult(path=virtual_path, error=None)

    def _virtualize_edit_result(self, result: EditResult, *, root: Path, prefix: str) -> EditResult:
        if result.error or not result.path:
            return EditResult(error=result.error, occurrences=result.occurrences)
        try:
            virtual_path = _virtualize_path(host_path=result.path, root=root, prefix=prefix or "/")
        except Exception:
            virtual_path = result.path
        return EditResult(path=virtual_path, error=None, occurrences=result.occurrences)

    def _virtualize_grep_matches(
        self,
        matches: list[GrepMatch],
        *,
        root: Path | None = None,
        prefix: str = "",
    ) -> list[GrepMatch]:
        root = root or self.workspace_root
        out: list[GrepMatch] = []
        for match in matches:
            try:
                virtual_path = _virtualize_path(host_path=match["path"], root=root, prefix=prefix or "/")
            except Exception:
                virtual_path = match["path"]
            out.append(
                GrepMatch(
                    path=virtual_path,
                    line_number=match["line_number"],
                    line=match["line"],
                )
            )
        return out

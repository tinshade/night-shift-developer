from __future__ import annotations

import os
import shutil
from pathlib import Path

from .base import MCPTool, ToolError, ToolRegistry


class FilesystemMCP:
    """Bounded filesystem operations for disposable repair workspaces."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.max_file_bytes = int(os.getenv("REPAIR_MAX_FILE_BYTES", "10485760"))
        self.max_workspace_bytes = int(os.getenv("REPAIR_MAX_WORKSPACE_BYTES", "524288000"))

    def _validate_path(self, path: str | Path) -> Path:
        target = (self.root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if self.root not in target.parents and target != self.root:
            raise ToolError(f"Path escapes workspace root: {path}")
        return target

    def create_workspace(self, guid: str) -> str:
        if not guid or Path(guid).name != guid:
            raise ToolError("Workspace GUID must be a non-empty single path component.")
        workspace = self._validate_path(guid)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "source").mkdir(exist_ok=True)
        (workspace / "generated").mkdir(exist_ok=True)
        (workspace / "logs").mkdir(exist_ok=True)
        return str(workspace)

    def copy_repository(self, source: str | Path, destination: str | Path) -> str:
        src = Path(source).resolve()
        dest = self._validate_path(destination)
        if not src.is_dir():
            raise ToolError(f"Source repository does not exist: {src}")
        if src == dest or src in dest.parents:
            raise ToolError("Repository destination cannot be inside the source repository.")
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            src,
            dest,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc"),
        )
        self._check_workspace_size(dest)
        return str(dest)

    def read_file(self, path: str | Path) -> str:
        target = self._validate_path(path)
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str | Path, content: str) -> str:
        target = self._validate_path(path)
        if len(content.encode("utf-8")) > self.max_file_bytes:
            raise ToolError(f"File exceeds the {self.max_file_bytes}-byte limit.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        self._check_workspace_size(target.parent)
        return str(target)

    def list_files(self, path: str | Path) -> list[str]:
        target = self._validate_path(path)
        return [str(item) for item in sorted(target.iterdir())]

    def delete_workspace(self, guid: str) -> bool:
        target = self._validate_path(guid)
        if target.exists():
            shutil.rmtree(target)
        return True

    def _check_workspace_size(self, path: Path) -> None:
        total = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        if total > self.max_workspace_bytes:
            raise ToolError(f"Workspace exceeds the {self.max_workspace_bytes}-byte limit.")


def build_filesystem_tools(filesystem: FilesystemMCP) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(MCPTool("create_workspace", "Create a repair workspace for a GUID.", filesystem.create_workspace))
    registry.register(MCPTool("copy_repository", "Copy repository contents into a workspace.", filesystem.copy_repository))
    registry.register(MCPTool("read_file", "Read a file from a safe workspace path.", filesystem.read_file))
    registry.register(MCPTool("write_file", "Write content to a safe workspace file.", filesystem.write_file))
    registry.register(MCPTool("list_files", "List files beneath a workspace path.", filesystem.list_files))
    registry.register(MCPTool("delete_workspace", "Delete a repair workspace safely.", filesystem.delete_workspace))
    return registry

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RepairAttempt:
    guid: str
    workspace: str
    source_path: str
    result_path: str
    status: str = "pending"
    summary: str = ""
    diagnostics: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    remaining_error: str = ""


class RepairSession:
    """A small, testable repair-session contract for later Docker and LLM phases."""

    def __init__(self, workspace_root: str, registry: Any | None = None):
        self.workspace_root = Path(workspace_root).resolve()
        self.registry = registry

    def begin(self, guid: str, source_repo: str | Path) -> RepairAttempt:
        if self.registry is None:
            raise RuntimeError("An MCP registry is required to begin a repair session.")

        workspace = str(self.registry.call("create_workspace", guid=guid))
        source_path = str(Path(workspace) / "source")
        self.registry.call("copy_repository", source=str(source_repo), destination=str(source_path))

        result_path = str(Path(workspace) / "result.json")
        result_payload = {
            "guid": guid,
            "status": "pending",
            "summary": "",
            "diagnostics": "",
            "files_changed": [],
            "tests_run": [],
            "remaining_error": "",
        }
        self.registry.call("write_file", path=result_path, content=json.dumps(result_payload, indent=2))

        return RepairAttempt(
            guid=guid,
            workspace=workspace,
            source_path=source_path,
            result_path=result_path,
        )

    def update_result(self, attempt: RepairAttempt, **payload: Any) -> RepairAttempt:
        record = json.loads(self.registry.call("read_file", path=attempt.result_path))
        record.update(payload)
        self.registry.call("write_file", path=attempt.result_path, content=json.dumps(record, indent=2))
        for key, value in payload.items():
            setattr(attempt, key, value)
        return attempt

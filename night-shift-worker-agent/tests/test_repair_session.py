import json
from pathlib import Path

from repair_session import RepairSession
from tools.mcp_registry import MCPRegistry


def test_repair_session_creates_workspace_and_result_file(tmp_path):
    registry = MCPRegistry(str(tmp_path))
    source_root = tmp_path / "source-repo"
    source_root.mkdir()
    (source_root / "README.md").write_text("hello", encoding="utf-8")

    session = RepairSession(workspace_root=str(tmp_path / "workspaces"), registry=registry)
    attempt = session.begin("guid-123", source_repo=source_root)

    assert Path(attempt.workspace).exists()
    assert Path(attempt.source_path).exists()
    assert Path(attempt.result_path).exists()
    assert (Path(attempt.source_path) / "README.md").read_text(encoding="utf-8") == "hello"

    session.update_result(attempt, status="fixed", summary="Patched it", files_changed=["README.md"])
    payload = json.loads(Path(attempt.result_path).read_text(encoding="utf-8"))
    assert payload["status"] == "fixed"
    assert payload["summary"] == "Patched it"

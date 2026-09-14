import json
from pathlib import Path

from repair_workflow import RepairWorkflow
from repair_runner import RepairDiagnostics
from tools.mcp_registry import MCPRegistry


class PassingRunner:
    def run(self, _guid, _source_path):
        return RepairDiagnostics(passed=True, output="ok", tests_run=["GET /health"])


def test_repair_workflow_records_stage_result(tmp_path):
    registry = MCPRegistry(str(tmp_path))
    source_root = tmp_path / "repo"
    source_root.mkdir()
    (source_root / "README.md").write_text("hello", encoding="utf-8")

    workflow = RepairWorkflow(
        workspace_root=str(tmp_path / "workspaces"),
        registry=registry,
        runner=PassingRunner(),
    )
    result = workflow.run("guid-42", source_repo=source_root, max_attempts=3)

    assert result.status == "fixed"
    assert result.tests_run == ["GET /health"]
    assert result.summary
    assert Path(workflow.session.registry.call("create_workspace", guid="probe")).exists()

from pathlib import Path

from main import RepairWorker, RepairResult
from repair_runner import IsolatedRepairRunner, RepairDiagnostics
from repair_workflow import RepairWorkflow
from tools.mcp_registry import MCPRegistry


class PassingRunner:
    def run(self, _guid, _source_path):
        return RepairDiagnostics(passed=True, output="health ok", tests_run=["GET /health"])


class FailingRunner:
    def run(self, _guid, _source_path):
        return RepairDiagnostics(passed=False, output="health failed", tests_run=["GET /health"])


class NoopLLM:
    def propose_and_apply(self, *_args):
        return {"status": "continue", "summary": "No patch available.", "files": []}


def make_source(tmp_path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("source", encoding="utf-8")
    return source


def test_successful_workflow_deletes_workspace(tmp_path):
    registry = MCPRegistry(str(tmp_path / "workspaces"))
    workflow = RepairWorkflow(str(tmp_path / "workspaces"), registry, runner=PassingRunner())

    result = workflow.run("success-guid", make_source(tmp_path))

    assert result.status == "fixed"
    assert result.cleanup_ok is True
    assert not (tmp_path / "workspaces" / "success-guid").exists()


def test_workflow_sends_configured_email_notification(tmp_path, monkeypatch):
    registry = MCPRegistry(str(tmp_path / "workspaces"))
    sent = []
    registry.registry.get("send_repair_result").handler = lambda **payload: sent.append(payload)
    monkeypatch.setenv("ENABLE_EMAIL_NOTIFICATIONS", "true")
    monkeypatch.setenv("REPAIR_NOTIFICATION_EMAIL", "developer@example.com")
    workflow = RepairWorkflow(str(tmp_path / "workspaces"), registry, runner=PassingRunner())

    result = workflow.run("email-guid", make_source(tmp_path))

    assert result.notification_error == ""
    assert sent[0]["status"] == "fixed"
    assert sent[0]["guid"] == "email-guid"


def test_workflow_notification_includes_original_stacktrace(tmp_path, monkeypatch):
    registry = MCPRegistry(str(tmp_path / "workspaces"))
    sent = []
    registry.registry.get("send_repair_result").handler = lambda **payload: sent.append(payload)
    monkeypatch.setenv("ENABLE_EMAIL_NOTIFICATIONS", "true")
    monkeypatch.setenv("REPAIR_NOTIFICATION_EMAIL", "developer@example.com")
    workflow = RepairWorkflow(str(tmp_path / "workspaces"), registry, runner=PassingRunner())

    workflow.run(
        "trace-guid",
        make_source(tmp_path),
        record={"message": "Database failure", "trace": "Traceback (most recent call last):\n  File \"app.py\", line 7"},
    )

    assert "Database failure" in sent[0]["diagnostics"]
    assert "Stacktrace:" in sent[0]["diagnostics"]
    assert "app.py" in sent[0]["diagnostics"]


def test_exhausted_workflow_is_terminal_and_cleans_workspace(tmp_path):
    registry = MCPRegistry(str(tmp_path / "workspaces"))
    workflow = RepairWorkflow(
        str(tmp_path / "workspaces"),
        registry,
        runner=FailingRunner(),
        llm_client=NoopLLM(),
    )

    result = workflow.run("failed-guid", make_source(tmp_path), max_attempts=2)

    assert result.status == "wontfix"
    assert result.remaining_error == "health failed"
    assert result.cleanup_ok is True
    assert not (tmp_path / "workspaces" / "failed-guid").exists()


class FakeDockerRegistry:
    def __init__(self):
        self.calls = []

    def call(self, tool_name, **kwargs):
        self.calls.append((tool_name, kwargs))
        if tool_name == "wait_for_health":
            return True
        if tool_name == "exec_command":
            return "health ok"
        if tool_name == "read_logs":
            return "logs"
        if tool_name == "remove_image":
            raise RuntimeError("image is in use")
        return True


def test_docker_runner_reports_cleanup_failure(tmp_path):
    source = tmp_path / "repo"
    (source / "dummy-api-server").mkdir(parents=True)
    (source / "dummy-api-server" / "Dockerfile").write_text("FROM python:3.12-slim", encoding="utf-8")
    registry = FakeDockerRegistry()

    result = IsolatedRepairRunner(registry).run("cleanup-guid", str(source))

    assert result.passed is True
    assert result.cleanup_ok is False
    assert "image is in use" in result.cleanup_error
    assert any(name == "remove_image" for name, _kwargs in registry.calls)


class FakeRedis:
    def __init__(self):
        self.record = {"status": "open", "error_fingerprint": "fingerprint"}
        self.client = self
        self.statuses = []
        self.metadata = {}

    def get(self, key):
        return "guid"

    def get_log(self, _guid):
        return self.record

    def set_status(self, _guid, status):
        self.statuses.append(status)
        self.record["status"] = status
        return True

    def update_metadata(self, _guid, **metadata):
        self.metadata.update(metadata)


def test_worker_failure_transitions_to_wontfix():
    redis_client = FakeRedis()
    worker = RepairWorker(redis_client)

    result = worker.process_guid("guid", lambda _guid, _record: (_ for _ in ()).throw(RuntimeError("boom")))

    assert isinstance(result, RepairResult)
    assert result.status == "wontfix"
    assert redis_client.statuses == ["in_progress", "wontfix"]
    assert redis_client.metadata["repair_error"] == "boom"

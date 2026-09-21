"""The repair client must READ the repository before proposing a patch."""

import json
import shutil
from pathlib import Path

import pytest

from repair_llm import LLMRepairClient
from tools.base import ToolError
from tools.mcp_registry import MCPRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeResponse:
    def __init__(self, content):
        self.content = content


class ScriptedLLM:
    """Returns queued responses in order and records every prompt it received."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts = []

    def invoke(self, messages):
        self.prompts.append(messages[1][1])
        return FakeResponse(self.responses.pop(0))


@pytest.fixture
def source(tmp_path):
    workspace_root = tmp_path / "workspaces"
    registry = MCPRegistry(str(workspace_root))
    source_path = workspace_root / "guid-1" / "source"
    source_path.mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "dummy-api-server",
        source_path / "dummy-api-server",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return registry, source_path


def test_model_is_shown_real_file_contents_before_patching(source):
    registry, source_path = source
    llm = ScriptedLLM(
        json.dumps({"reason": "the create route is implicated", "files": ["main.py"]}),
        json.dumps(
            {
                "status": "fixed",
                "summary": "Guard against a non-string first_name.",
                "edits": [
                    {
                        "path": "main.py",
                        "old": "        formatted_name = user_payload.first_name.title()",
                        "new": "        formatted_name = str(user_payload.first_name or \"\").title()",
                    }
                ],
            }
        ),
    )
    client = LLMRepairClient(registry, llm=llm)

    result = client.propose_and_apply(
        {"message": "Error while creating user", "trace": "AttributeError"},
        "validation failed",
        str(source_path),
    )

    # Phase 1 sees the file tree, phase 2 sees the actual source.
    assert "main.py" in llm.prompts[0]
    assert "user_payload.first_name.title()" in llm.prompts[1]

    assert result["status"] == "fixed"
    assert result["files_changed"] == ["main.py"]
    patched = (source_path / "dummy-api-server" / "main.py").read_text(encoding="utf-8")
    assert 'str(user_payload.first_name or "").title()' in patched
    assert patched.count("def delete_user") == 1  # the rest of the file survived


def test_hallucinated_edit_is_rejected_not_written(source):
    registry, source_path = source
    llm = ScriptedLLM(
        json.dumps({"reason": "guessing", "files": ["main.py"]}),
        json.dumps(
            {
                "status": "fixed",
                "summary": "Invented a line that is not in the file.",
                "edits": [{"path": "main.py", "old": "this_line_does_not_exist()", "new": "pass"}],
            }
        ),
    )
    client = LLMRepairClient(registry, llm=llm)
    before = (source_path / "dummy-api-server" / "main.py").read_text(encoding="utf-8")

    with pytest.raises(ToolError, match="not found verbatim"):
        client.propose_and_apply({"message": "boom"}, "validation failed", str(source_path))

    after = (source_path / "dummy-api-server" / "main.py").read_text(encoding="utf-8")
    assert after == before


def test_expected_404_is_declined_rather_than_patched(source):
    registry, source_path = source
    llm = ScriptedLLM(
        json.dumps({"reason": "delete route", "files": ["main.py"]}),
        json.dumps(
            {
                "status": "wontfix",
                "summary": "A 404 for a missing user is correct behaviour, not a defect.",
                "edits": [],
            }
        ),
    )
    client = LLMRepairClient(registry, llm=llm)
    before = (source_path / "dummy-api-server" / "main.py").read_text(encoding="utf-8")

    result = client.propose_and_apply(
        {"message": "Tried to delete a non-existing user with id 4728193"},
        "validation failed",
        str(source_path),
    )

    assert result["status"] == "wontfix"
    assert result["files_changed"] == []
    assert (source_path / "dummy-api-server" / "main.py").read_text(encoding="utf-8") == before

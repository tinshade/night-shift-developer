"""End-to-end proof that a seeded bug is a fixable, reproducible target.

For each bug in the catalogue:
  1. seed it into a throwaway copy of the repo,
  2. confirm the copy is in the 'seeded' state,
  3. hand the LLM repair client the file (with a scripted model that returns
     the correct one-line edit),
  4. confirm the copy is back in the 'clean' state.

Step 3 uses a scripted model so the test is deterministic and needs no Groq
credits. It exercises the real selection -> read -> exact-match-edit -> write
path, which is what a live model would go through.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from repair_llm import LLMRepairClient
from tools.mcp_registry import MCPRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "mess-maker"))

from bug_catalogue import CATALOGUE, bug_state  # noqa: E402


class FakeResponse:
    def __init__(self, content):
        self.content = content


class ScriptedLLM:
    def __init__(self, *responses):
        self.responses = list(responses)

    def invoke(self, messages):
        return FakeResponse(self.responses.pop(0))


@pytest.fixture
def workspace(tmp_path):
    workspace_root = tmp_path / "workspaces"
    registry = MCPRegistry(str(workspace_root))
    source_path = workspace_root / "guid-1" / "source"
    source_path.mkdir(parents=True)
    shutil.copytree(
        REPO_ROOT / "dummy-api-server",
        source_path / "dummy-api-server",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log"),
    )
    return registry, source_path


@pytest.mark.parametrize("bug_id", sorted(CATALOGUE))
def test_seeded_bug_can_be_reproduced_and_repaired(workspace, bug_id):
    registry, source_path = workspace
    bug = CATALOGUE[bug_id]
    target = source_path / bug.file

    # The catalogue must match the shipped source exactly.
    assert bug_state(bug, source_path) == "clean", (
        f"{bug_id}: the baseline copy is not clean. The snippet in "
        f"bug_catalogue.py has drifted from {bug.file}."
    )

    # 1-2. Seed the defect.
    text = target.read_text(encoding="utf-8")
    assert text.count(bug.fixed) == 1, f"{bug_id}: 'fixed' snippet is not unique"
    target.write_text(text.replace(bug.fixed, bug.broken, 1), encoding="utf-8")
    assert bug_state(bug, source_path) == "seeded"

    # 3. Repair it through the real client path.
    relative = str(Path(bug.file).relative_to("dummy-api-server"))
    llm = ScriptedLLM(
        json.dumps({"reason": bug.symptom, "files": [relative]}),
        json.dumps({
            "status": "fixed",
            "summary": f"Repair {bug_id}: {bug.title}",
            "edits": [{"path": relative, "old": bug.broken, "new": bug.fixed}],
        }),
    )
    result = LLMRepairClient(registry, llm=llm).propose_and_apply(
        {"message": bug.symptom},
        f"FAILED tests/test_api_contract.py::{bug.test}",
        str(source_path),
    )

    # 4. Back to clean.
    assert result["status"] == "fixed"
    assert result["files_changed"] == [relative]
    assert bug_state(bug, source_path) == "clean", f"{bug_id}: repair did not restore the file"

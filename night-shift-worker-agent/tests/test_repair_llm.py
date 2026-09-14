import json
import sys
import types

import pytest

from repair_llm import LLMRepairClient
from groq_models import create_groq_model
from tools.base import ToolError
from tools.mcp_registry import MCPRegistry


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, content):
        self.content = content
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return FakeResponse(self.content)


def test_groq_response_applies_structured_patch(tmp_path):
    workspace_root = tmp_path / "workspaces"
    registry = MCPRegistry(str(workspace_root))
    source = workspace_root / "source"
    source.mkdir(parents=True)
    llm = FakeLLM(
        "```json\n"
        + json.dumps({
            "status": "fixed",
            "summary": "Patched the source.",
            "files": [{"path": "app.py", "content": "print('fixed')\n"}],
        })
        + "\n```"
    )
    client = LLMRepairClient(registry, llm=llm)

    result = client.propose_and_apply({"guid": "guid-1"}, "test failed", str(source))

    assert result["status"] == "fixed"
    assert (source / "app.py").read_text(encoding="utf-8") == "print('fixed')\n"
    assert llm.messages[0][0] == "system"
    assert llm.messages[1][0] == "human"


def test_groq_configuration_is_required(monkeypatch, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_FREE_MODEL", raising=False)
    client = LLMRepairClient(MCPRegistry(str(tmp_path / "workspaces")))

    with pytest.raises(ToolError, match="GROQ_API_KEY and GROQ_FREE_MODEL"):
        client.propose_and_apply({}, "diagnostics", str(tmp_path))


def test_groq_rejects_unsafe_patch_path(tmp_path):
    workspace_root = tmp_path / "workspaces"
    registry = MCPRegistry(str(workspace_root))
    source = workspace_root / "source"
    source.mkdir(parents=True)
    llm = FakeLLM(json.dumps({
        "status": "fixed",
        "summary": "unsafe",
        "files": [{"path": "../outside.py", "content": "bad"}],
    }))
    client = LLMRepairClient(registry, llm=llm)

    with pytest.raises(ToolError, match="outside the repair source"):
        client.propose_and_apply({}, "diagnostics", str(source))


def test_model_roles_use_separate_free_model_settings(monkeypatch):
    created = []

    def fake_init_chat_model(**kwargs):
        created.append(kwargs)
        return object()

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_CODE_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("GROQ_OPERATIONS_MODEL", "openai/gpt-oss-20b")
    chat_models = types.ModuleType("langchain.chat_models")
    chat_models.init_chat_model = fake_init_chat_model
    langchain = types.ModuleType("langchain")
    langchain.chat_models = chat_models
    monkeypatch.setitem(sys.modules, "langchain", langchain)
    monkeypatch.setitem(sys.modules, "langchain.chat_models", chat_models)

    create_groq_model("code")
    create_groq_model("operations")

    assert [item["model"] for item in created] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert all(item["model_provider"] == "groq" for item in created)

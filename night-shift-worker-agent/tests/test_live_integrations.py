import os
from pathlib import Path

import pytest


RUN_LIVE = os.getenv("RUN_LIVE_INTEGRATION_TESTS", "false").lower() == "true"


@pytest.mark.skipif(not RUN_LIVE, reason="Set RUN_LIVE_INTEGRATION_TESTS=true to enable live integrations.")
def test_live_groq_configuration_and_response():
    from repair_llm import LLMRepairClient
    from tools.mcp_registry import MCPRegistry

    api_key = os.environ["GROQ_API_KEY"]
    model = os.environ["GROQ_FREE_MODEL"]
    client = LLMRepairClient(MCPRegistry(str(Path.cwd() / "live-workspaces")), api_key=api_key, model=model)
    response = client._get_llm().invoke("Reply with the single word READY.")

    assert response.content


@pytest.mark.skipif(not RUN_LIVE, reason="Set RUN_LIVE_INTEGRATION_TESTS=true to enable live integrations.")
def test_live_github_configuration():
    from tools.github_mcp import GitHubMCP

    github = GitHubMCP()
    assert github._request("GET", f"/repos/{github.owner}/{github.repository}")["full_name"]


@pytest.mark.skipif(not RUN_LIVE, reason="Set RUN_LIVE_INTEGRATION_TESTS=true to enable live integrations.")
def test_live_email_configuration():
    from tools.email_mcp import EmailMCP

    result = EmailMCP().send_repair_result(
        recipient=os.environ["REPAIR_NOTIFICATION_EMAIL"],
        status="fixed",
        guid="live-integration-check",
        summary="Live email integration check.",
    )

    assert result["sent"] is True

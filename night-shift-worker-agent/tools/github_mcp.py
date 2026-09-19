from __future__ import annotations

import json
import os
import subprocess
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from groq_models import create_groq_model
from .base import MCPTool, ToolError, ToolRegistry


class GitHubMCP:
    """Small authenticated GitHub adapter for validated repair workspaces."""

    def __init__(self, base_branch: str = "dev", token: str | None = None, owner: str | None = None, repository: str | None = None, drafting_llm=None):
        self.base_branch = base_branch
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
        self.owner = owner or os.getenv("GITHUB_OWNER")
        self.repository = repository or os.getenv("GITHUB_REPOSITORY")
        self.api_url = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        self.drafting_llm = drafting_llm

    def _pull_request_body(self, branch_name: str) -> str:
        fallback = "Automated repair validated in an isolated environment."
        if os.getenv("ENABLE_GROQ_OPERATIONS_DRAFTING", "false").lower() != "true":
            return fallback
        llm = self.drafting_llm or create_groq_model("operations")
        response = llm.invoke([
            ("system", "Draft a concise factual GitHub pull request body for an automated code repair."),
            ("human", f"Branch: {branch_name}\nBase branch: {self.base_branch}\nDo not invent test results."),
        ])
        content = getattr(response, "content", response)
        if not isinstance(content, str) or not content.strip():
            raise ToolError("Operations model returned an empty pull request draft.")
        return content.strip()

    def _require_config(self) -> None:
        if not self.token or not self.owner or not self.repository:
            raise ToolError("GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_REPOSITORY are required.")

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        self._require_config()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.api_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ToolError(f"GitHub request failed ({exc.code}): {detail}") from exc
        except (URLError, json.JSONDecodeError) as exc:
            raise ToolError(f"GitHub request failed: {exc}") from exc

    def _git(self, workspace: str, args: list[str]) -> str:
        try:
            completed = subprocess.run(
                ["git", *args], cwd=workspace, check=True, capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = getattr(exc, "stderr", "") or str(exc)
            raise ToolError(f"Git operation failed: {detail}") from exc
        return completed.stdout.strip()

    def create_branch(self, branch_name: str, from_branch: str | None = None) -> str:
        if not branch_name:
            raise ToolError("Branch name is required.")
        source = from_branch or self.base_branch
        ref = self._request("GET", f"/repos/{self.owner}/{self.repository}/git/ref/heads/{source}")
        self._request(
            "POST",
            f"/repos/{self.owner}/{self.repository}/git/refs",
            {"ref": f"refs/heads/{branch_name}", "sha": ref["object"]["sha"]},
        )
        return branch_name

    def commit_changes(self, message: str, files: list[str] | None = None, workspace: str | None = None) -> str:
        if not message:
            raise ToolError("Commit message is required.")
        if not workspace:
            raise ToolError("Workspace is required for a commit.")
        self._git(workspace, ["add", *(files or ["."])])
        if not self._git(workspace, ["status", "--porcelain"]):
            raise ToolError("Repair workspace contains no changes to commit.")
        self._git(workspace, ["commit", "--message", message])
        return self._git(workspace, ["rev-parse", "HEAD"])

    def checkout_branch(self, workspace: str, branch_name: str, from_branch: str | None = None) -> str:
        if not branch_name:
            raise ToolError("Branch name is required.")
        return self._git(workspace, ["checkout", "-b", branch_name, from_branch or self.base_branch])

    def push_branch(self, branch_name: str, workspace: str | None = None) -> str:
        if not branch_name:
            raise ToolError("Branch name is required.")
        if not workspace:
            raise ToolError("Workspace is required to push a branch.")
        self._git(workspace, ["push", "origin", branch_name])
        return f"origin/{branch_name}"

    def create_pull_request(self, branch_name: str, target_branch: str | None = None) -> str:
        if not branch_name:
            raise ToolError("Branch name is required.")
        response = self._request(
            "POST",
            f"/repos/{self.owner}/{self.repository}/pulls",
            {
                "title": f"Night Shift repair: {branch_name}",
                "head": branch_name,
                "base": target_branch or self.base_branch,
                "body": self._pull_request_body(branch_name),
            },
        )
        return response["html_url"]

    def publish_repair(
        self,
        workspace: str,
        branch_name: str,
        message: str,
        files: list[str] | None = None,
        target_branch: str | None = None,
    ) -> str:
        """Publish only a locally changed, already validated repair workspace."""
        if not workspace:
            raise ToolError("Workspace is required for publication.")
        if not branch_name:
            raise ToolError("Branch name is required for publication.")
        if not self._git(workspace, ["status", "--porcelain"]):
            raise ToolError("Repair workspace contains no changes to publish.")
        target = target_branch or self.base_branch
        self.create_branch(branch_name, target)
        self.checkout_branch(workspace, branch_name, target)
        self.commit_changes(message, files=files, workspace=workspace)
        self.push_branch(branch_name, workspace=workspace)
        return self.create_pull_request(branch_name, target)


def build_github_tools(github: GitHubMCP) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(MCPTool("create_branch", "Create a branch for a validated repair.", github.create_branch))
    registry.register(MCPTool("commit_changes", "Commit the repair workspace changes.", github.commit_changes))
    registry.register(MCPTool("checkout_branch", "Checkout a local branch for a repair.", github.checkout_branch))
    registry.register(MCPTool("push_branch", "Push the repair branch to origin.", github.push_branch))
    registry.register(MCPTool("create_pull_request", "Create a PR against the dev branch.", github.create_pull_request))
    registry.register(MCPTool("publish_repair", "Publish a validated repair as a GitHub pull request.", github.publish_repair))
    return registry

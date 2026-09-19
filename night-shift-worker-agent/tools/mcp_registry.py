from __future__ import annotations

from .base import ToolRegistry
from .docker_mcp import DockerMCP, build_docker_tools
from .email_mcp import EmailMCP, build_email_tools
from .filesystem_mcp import FilesystemMCP, build_filesystem_tools
from .github_mcp import GitHubMCP, build_github_tools


class MCPRegistry:
    """Aggregate MCP tool registries for the worker layer."""

    def __init__(self, workspace_root: str):
        self.filesystem = FilesystemMCP(workspace_root)
        self.docker = DockerMCP()
        self.email = EmailMCP()
        self.github = GitHubMCP()

        self.registry = ToolRegistry()
        for registry in (
            build_filesystem_tools(self.filesystem),
            build_docker_tools(self.docker),
            build_email_tools(self.email),
            build_github_tools(self.github),
        ):
            for name in registry.names():
                self.registry.register(registry.get(name))

    def call(self, tool_name: str, **kwargs):
        return self.registry.call(tool_name, **kwargs)

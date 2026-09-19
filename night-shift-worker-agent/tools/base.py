from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ToolError(RuntimeError):
    """Raised when an MCP tool cannot execute safely."""


@dataclass
class MCPTool:
    name: str
    description: str
    handler: Callable[..., Any]
    enabled: bool = True

    def call(self, **kwargs: Any) -> Any:
        if not self.enabled:
            raise ToolError(f"Tool '{self.name}' is disabled.")
        return self.handler(**kwargs)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, MCPTool] = {}

    def register(self, tool: MCPTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> MCPTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Unknown tool '{name}'.") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    def call(self, tool_name: str, **kwargs: Any) -> Any:
        return self.get(tool_name).call(**kwargs)

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from groq_models import create_groq_model
from tools.base import ToolError


class LLMRepairClient:
    """Groq LangChain client that applies only structured workspace patches."""

    def __init__(self, registry, api_key: str | None = None, model: str | None = None, llm: Any | None = None):
        self.registry = registry
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_CODE_MODEL") or os.getenv("GROQ_FREE_MODEL")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))
        self.llm = llm

    def _get_llm(self):
        if self.llm is not None:
            return self.llm
        if not self.api_key or not self.model:
            raise ToolError("GROQ_API_KEY and GROQ_FREE_MODEL are required for repair attempts.")
        self.llm = create_groq_model("code", api_key=self.api_key, model=self.model)
        return self.llm

    @staticmethod
    def _response_text(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        raise ToolError("Groq returned a response without text content.")

    @staticmethod
    def _parse_result(content: str) -> dict:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(lines[1:-1]).strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Groq returned invalid repair JSON: {exc}") from exc
        if not isinstance(result, dict):
            raise ToolError("Groq repair response must be a JSON object.")
        return result

    def propose_and_apply(self, record: dict, diagnostics: str, source_path: str) -> dict:
        prompt = {
            "error_record": record,
            "diagnostics": diagnostics,
            "instruction": (
                "Return JSON only with status, summary, and files. Each file must contain "
                "a relative path and complete replacement content. Use status=continue when "
                "more diagnosis is needed and status=fixed only when the patch should resolve "
                "the failure. Allowed statuses: fixed, continue, wontfix."
            ),
        }
        try:
            response = self._get_llm().invoke([
                (
                    "system",
                    "You are a repair agent. Never propose changes outside the supplied repository copy. Return JSON only.",
                ),
                ("human", json.dumps(prompt)),
            ])
            result = self._parse_result(self._response_text(response))
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Groq repair request failed: {exc}") from exc

        if result.get("status") not in {"fixed", "continue", "wontfix"}:
            raise ToolError("LLM repair result has an unsupported status.")
        for file_change in result.get("files", []):
            relative_path = Path(file_change.get("path", ""))
            if not relative_path.parts or relative_path.is_absolute() or ".." in relative_path.parts:
                raise ToolError("LLM returned a file path outside the repair source.")
            content = file_change.get("content")
            if not isinstance(content, str):
                raise ToolError("LLM returned a file without text content.")
            self.registry.call("write_file", path=str(Path(source_path) / relative_path), content=content)
        return result

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from groq_models import create_groq_model
from tools.base import ToolError

logger = logging.getLogger("night-shift-repair-llm")

# --- Free-tier budget guards -------------------------------------------------
# Groq free tier for openai/gpt-oss-*: 30 RPM, 8_000 TPM, 200_000 TPD.
# Everything below is sized so a single repair attempt stays under ~6k tokens.
MAX_DIAGNOSTICS_CHARS = int(os.getenv("LLM_MAX_DIAGNOSTICS_CHARS", "6000"))
MAX_CONTEXT_FILE_CHARS = int(os.getenv("LLM_MAX_CONTEXT_FILE_CHARS", "12000"))
MAX_SELECTED_FILES = int(os.getenv("LLM_MAX_SELECTED_FILES", "3"))
TARGET_SUBDIR = os.getenv("REPAIR_TARGET_SUBDIR", "dummy-api-server")
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".pytest_cache", "tests"}

SELECT_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "files": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["reason", "files"],
    "additionalProperties": False,
}

PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["fixed", "continue", "wontfix"]},
        "summary": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["status", "summary", "edits"],
    "additionalProperties": False,
}

SELECT_SYSTEM = (
    "You are triaging a failure in a Python repository. You are shown the error record, "
    "the validation output, and the repository file tree. Name the files you must READ to "
    "diagnose the failure. Do not guess a fix yet. Return JSON only."
)

PATCH_SYSTEM = (
    "You are a repair agent working on a copy of a Python repository.\n"
    "You are given the full current contents of the relevant files.\n"
    "Propose the SMALLEST correct change as a list of exact search/replace edits.\n"
    "\n"
    "Rules for every edit:\n"
    "  - 'old' MUST be copied byte-for-byte from the file shown to you, including indentation.\n"
    "  - 'old' MUST appear EXACTLY ONCE in that file. Include surrounding lines if needed to\n"
    "    make it unique.\n"
    "  - 'new' is the replacement text. Keep the same indentation style.\n"
    "  - Never invent files, functions, or imports you have not seen.\n"
    "  - If the application behaviour is already correct and the 'error' is a normal, expected\n"
    "    condition (for example a 404 for a record that does not exist), return status 'wontfix'\n"
    "    with an empty edits list and explain why in the summary.\n"
    "\n"
    "status: 'fixed' when the edits should resolve the failure, 'continue' when more diagnosis\n"
    "is needed, 'wontfix' when nothing should change. Return JSON only."
)


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    return f"{text[:head]}\n\n...[{len(text) - limit} chars elided]...\n\n{text[-tail:]}"


class LLMRepairClient:
    """Groq client that reads the repository before proposing minimal, verified edits."""

    def __init__(self, registry, api_key: str | None = None, model: str | None = None, llm: Any | None = None):
        self.registry = registry
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_CODE_MODEL") or os.getenv("GROQ_FREE_MODEL")
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))
        self.llm = llm

    # -- model plumbing -------------------------------------------------------

    def _get_llm(self):
        if self.llm is not None:
            return self.llm
        if not self.api_key or not self.model:
            raise ToolError("GROQ_API_KEY and GROQ_CODE_MODEL are required for repair attempts.")
        self.llm = create_groq_model(
            "code",
            api_key=self.api_key,
            model=self.model,
            max_tokens=self.max_tokens,
        )
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
    def _extract_json(content: str) -> dict:
        """Parse JSON even when the model wraps it in prose or fences."""
        cleaned = (content or "").strip()
        # Strip reasoning blocks some gpt-oss configurations emit into content.
        if "</think>" in cleaned:
            cleaned = cleaned.rsplit("</think>", 1)[1].strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.rstrip().endswith("```"):
                cleaned = cleaned.rstrip()[:-3]
            cleaned = cleaned.strip()
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start == -1 or end <= start:
                raise ToolError(f"Groq returned no JSON object. First 300 chars: {cleaned[:300]!r}")
            try:
                result = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ToolError(f"Groq returned invalid repair JSON: {exc}") from exc
        if not isinstance(result, dict):
            raise ToolError("Groq repair response must be a JSON object.")
        return result

    def _invoke_json(self, system: str, human: str, schema: dict, schema_name: str) -> dict:
        """Call Groq with strict JSON schema, degrading gracefully, retrying on 429."""
        llm = self._get_llm()
        formats = [
            {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
            {"type": "json_object"},
            None,
        ]
        last_error: Exception | None = None
        for response_format in formats:
            try:
                bound = llm.bind(response_format=response_format) if response_format else llm
            except (AttributeError, TypeError):
                bound = llm  # test doubles and wrappers without .bind()
            for attempt in range(4):
                try:
                    response = bound.invoke([("system", system), ("human", human)])
                    return self._extract_json(self._response_text(response))
                except Exception as exc:  # noqa: BLE001 - provider errors are untyped
                    last_error = exc
                    text = str(exc)
                    if "429" in text or "rate_limit" in text.lower():
                        delay = 8 * (attempt + 1)
                        logger.warning("Groq rate limited, sleeping %ss", delay)
                        time.sleep(delay)
                        continue
                    if "response_format" in text or "json_schema" in text:
                        break  # try the next, less strict format
                    if attempt == 3:
                        break
                    time.sleep(2)
        raise ToolError(f"Groq repair request failed: {last_error}")

    # -- repository context ---------------------------------------------------

    def _target_root(self, source_path: str) -> Path:
        root = Path(source_path) / TARGET_SUBDIR
        return root if root.is_dir() else Path(source_path)

    def _file_tree(self, root: Path) -> list[str]:
        entries = []
        for path in sorted(root.rglob("*.py")):
            if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
                continue
            entries.append(f"{path.relative_to(root)} ({path.stat().st_size} bytes)")
        return entries

    def _read_files(self, root: Path, relative_paths: list[str]) -> dict[str, str]:
        contents: dict[str, str] = {}
        budget = MAX_CONTEXT_FILE_CHARS
        for relative in relative_paths[:MAX_SELECTED_FILES]:
            candidate = Path(relative)
            if candidate.is_absolute() or ".." in candidate.parts:
                continue
            target = root / candidate
            if not target.is_file():
                logger.warning("Model asked for a file that does not exist: %s", relative)
                continue
            text = self.registry.call("read_file", path=str(target))
            if len(text) > budget:
                text = _truncate(text, budget)
            contents[str(candidate)] = text
            budget -= len(text)
            if budget <= 0:
                break
        return contents

    # -- edit application -----------------------------------------------------

    def _apply_edits(self, root: Path, edits: list[dict], contents: dict[str, str]) -> tuple[list[str], list[str]]:
        changed: list[str] = []
        problems: list[str] = []
        buffers = dict(contents)

        for edit in edits:
            relative = Path(str(edit.get("path", "")))
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                problems.append(f"rejected path outside the repair source: {edit.get('path')!r}")
                continue
            key = str(relative)
            if key not in buffers:
                target = root / relative
                if not target.is_file():
                    problems.append(f"file does not exist: {key}")
                    continue
                buffers[key] = self.registry.call("read_file", path=str(target))

            old, new = edit.get("old"), edit.get("new")
            if not isinstance(old, str) or not isinstance(new, str):
                problems.append(f"{key}: edit is missing text for 'old' or 'new'")
                continue
            if not old:
                problems.append(f"{key}: 'old' was empty; refusing to rewrite the whole file")
                continue

            occurrences = buffers[key].count(old)
            if occurrences == 0:
                problems.append(f"{key}: 'old' text not found verbatim: {old[:120]!r}")
                continue
            if occurrences > 1:
                problems.append(f"{key}: 'old' text is ambiguous ({occurrences} matches): {old[:120]!r}")
                continue
            buffers[key] = buffers[key].replace(old, new, 1)
            if key not in changed:
                changed.append(key)

        for key in changed:
            self.registry.call("write_file", path=str(root / key), content=buffers[key])
            logger.info("Applied repair edit to %s", key)
        return changed, problems

    # -- public API -----------------------------------------------------------

    def propose_and_apply(
        self,
        record: dict,
        diagnostics: str,
        source_path: str,
        last_failure: str = "",
    ) -> dict:
        root = self._target_root(source_path)
        diagnostics = _truncate(diagnostics, MAX_DIAGNOSTICS_CHARS)
        error_summary = {
            "message": record.get("message", ""),
            "exception_type": record.get("exception_type", ""),
            "trace": _truncate(record.get("trace", ""), 2000),
            "application": record.get("application", ""),
        }

        # Phase 1 - let the model choose what it needs to read.
        selection = self._invoke_json(
            SELECT_SYSTEM,
            json.dumps(
                {
                    "error_record": error_summary,
                    "validation_output": diagnostics,
                    "repository_files": self._file_tree(root),
                    "instruction": f"Return at most {MAX_SELECTED_FILES} file paths, relative to the repository root.",
                },
                indent=2,
            ),
            SELECT_SCHEMA,
            "file_selection",
        )
        selected = [str(item) for item in selection.get("files", []) if isinstance(item, str)]
        contents = self._read_files(root, selected)
        if not contents:
            raise ToolError(f"The model selected no readable files (asked for: {selected}).")
        logger.info("Repair context: %s", list(contents))

        # Phase 2 - propose minimal edits against the real file contents.
        patch_payload: dict[str, Any] = {
            "error_record": error_summary,
            "validation_output": diagnostics,
            "files": [{"path": path, "content": text} for path, text in contents.items()],
        }
        if last_failure:
            patch_payload["previous_attempt_failed_because"] = _truncate(last_failure, 1500)

        result = self._invoke_json(
            PATCH_SYSTEM,
            json.dumps(patch_payload, indent=2),
            PATCH_SCHEMA,
            "repair_patch",
        )

        status = result.get("status")
        if status not in {"fixed", "continue", "wontfix"}:
            raise ToolError(f"LLM repair result has an unsupported status: {status!r}")

        edits = result.get("edits") or []
        if not isinstance(edits, list):
            raise ToolError("LLM repair result 'edits' must be a list.")

        changed, problems = self._apply_edits(root, edits, contents)
        if problems and not changed:
            raise ToolError("No edit could be applied: " + "; ".join(problems))
        if problems:
            logger.warning("Some edits were skipped: %s", "; ".join(problems))

        result["files"] = [{"path": path} for path in changed]
        result["files_changed"] = changed
        result["edit_problems"] = problems
        return result

from __future__ import annotations

import json
import os
import re
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from repair_llm import LLMRepairClient
from repair_runner import IsolatedRepairRunner, RepairDiagnostics
from repair_session import RepairSession

logger = logging.getLogger("night-shift-repair-workflow")


@dataclass
class RepairWorkflowResult:
    status: str
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    remaining_error: str = ""
    pr_url: str = ""
    cleanup_ok: bool = True
    cleanup_error: str = ""
    notification_error: str = ""


class RepairWorkflow:
    """Run bounded isolated validation and optional patch attempts."""

    def __init__(self, workspace_root: str, registry: Any, runner: Any | None = None, llm_client: Any | None = None):
        self.session = RepairSession(workspace_root=workspace_root, registry=registry)
        self.registry = registry
        self.runner = runner or IsolatedRepairRunner(registry, int(os.getenv("REPAIR_TIMEOUT_SECONDS", "600")))
        self.llm_client = llm_client or LLMRepairClient(registry)

    @staticmethod
    def _repair_branch_name(guid: str, record: dict) -> str:
        error_text = record.get("message") or record.get("exception_type") or "application-error"
        slug = re.sub(r"[^a-z0-9]+", "-", error_text.lower()).strip("-")[:60]
        slug = slug or "application-error"
        return f"ai-fix/{slug}-{guid[:8]}"

    @staticmethod
    def _notification_diagnostics(record: dict, repair_diagnostics: str) -> str:
        sections = []
        if record.get("message"):
            sections.append(f"Original error:\n{record['message']}")
        if record.get("trace"):
            sections.append(f"Stacktrace:\n{record['trace']}")
        if repair_diagnostics:
            sections.append(f"Repair diagnostics:\n{repair_diagnostics}")
        return "\n\n".join(sections)

    def run(self, guid: str, source_repo: str | Path, record: dict | None = None, *, max_attempts: int | None = None) -> RepairWorkflowResult:
        attempt = self.session.begin(guid=guid, source_repo=source_repo)
        max_attempts = max_attempts or int(os.getenv("MAX_REPAIR_ATTEMPTS", "3"))
        record = record or {}
        final = RepairWorkflowResult(status="wontfix", summary="Repair attempts were exhausted.")
        cleanup_errors: list[str] = []

        for attempt_index in range(max_attempts):
            logger.info("Starting repair attempt guid=%s attempt=%s/%s", guid, attempt_index + 1, max_attempts)
            try:
                diagnostics = self.runner.run(guid, attempt.source_path)
            except Exception as exc:
                diagnostics = RepairDiagnostics(
                    passed=False,
                    output=f"Repair runner failed: {exc}",
                    cleanup_ok=False,
                    cleanup_error=f"Repair runner failed: {exc}",
                )
            self.session.update_result(
                attempt,
                status="in_progress",
                summary=f"Repair attempt {attempt_index + 1}/{max_attempts}",
                diagnostics=diagnostics.output,
                tests_run=diagnostics.tests_run,
            )
            if not diagnostics.cleanup_ok:
                cleanup_errors.append(diagnostics.cleanup_error)
            if diagnostics.passed:
                logger.info("Repair validation passed guid=%s", guid)
                final = RepairWorkflowResult(
                    status="fixed",
                    summary="Validation passed in the isolated repair environment.",
                    tests_run=diagnostics.tests_run,
                )
                if os.getenv("ENABLE_GITHUB_REPAIR", "false").lower() == "true":
                    try:
                        branch = self._repair_branch_name(guid, record)
                        final.pr_url = self.registry.call(
                            "publish_repair",
                            workspace=attempt.source_path,
                            branch_name=branch,
                            message=f"Repair {guid}",
                        )
                    except Exception as exc:
                        final.summary = f"Validation passed, but GitHub publication failed: {exc}"
                break
            if attempt_index == max_attempts - 1:
                final = RepairWorkflowResult(
                    status="wontfix",
                    summary="Repair attempts were exhausted.",
                    tests_run=diagnostics.tests_run,
                    remaining_error=diagnostics.output,
                )
                break
            try:
                logger.info("Requesting Groq repair patch guid=%s", guid)
                patch = self.llm_client.propose_and_apply(record, diagnostics.output, attempt.source_path)
            except Exception as exc:
                final = RepairWorkflowResult(status="wontfix", summary=f"LLM repair failed: {exc}", remaining_error=diagnostics.output)
                break
            self.session.update_result(
                attempt,
                summary=patch.get("summary", "LLM patch applied."),
                files_changed=[item.get("path", "") for item in patch.get("files", [])],
            )
            if patch.get("status") == "wontfix":
                final = RepairWorkflowResult(status="wontfix", summary=patch.get("summary", "LLM declined repair."), remaining_error=diagnostics.output)
                break

        result = json.loads(self.session.registry.call("read_file", path=attempt.result_path))
        final.files_changed = result.get("files_changed") or final.files_changed
        final.tests_run = result.get("tests_run") or final.tests_run
        final.remaining_error = result.get("remaining_error") or final.remaining_error
        final.cleanup_error = "\n".join(error for error in cleanup_errors if error)
        final.cleanup_ok = not final.cleanup_error
        if os.getenv("ENABLE_EMAIL_NOTIFICATIONS", "false").lower() == "true":
            recipient = os.getenv("REPAIR_NOTIFICATION_EMAIL") or os.getenv("GOOGLE_EMAIL_ID")
            try:
                if not recipient:
                    raise RuntimeError("REPAIR_NOTIFICATION_EMAIL or GOOGLE_EMAIL_ID is required.")
                self.registry.call(
                    "send_repair_result",
                    recipient=recipient,
                    status=final.status,
                    guid=guid,
                    summary=final.summary,
                    pr_url=final.pr_url or None,
                    diagnostics=self._notification_diagnostics(record, final.remaining_error) or None,
                )
            except Exception as exc:
                final.notification_error = str(exc)
        self.session.update_result(
            attempt,
            status=final.status,
            summary=final.summary,
            remaining_error=final.remaining_error,
            cleanup_ok=final.cleanup_ok,
            cleanup_error=final.cleanup_error,
            notification_error=final.notification_error,
        )
        try:
            self.registry.call("delete_workspace", guid=guid)
        except Exception as exc:
            final.cleanup_ok = False
            final.cleanup_error = "\n".join(filter(None, [final.cleanup_error, f"delete_workspace {guid}: {exc}"]))
        logger.info("Repair workflow completed guid=%s status=%s", guid, final.status)
        return final

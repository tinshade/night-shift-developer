from __future__ import annotations

import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Callable

from groq_models import create_groq_model
from .base import MCPTool, ToolError, ToolRegistry


class EmailMCP:
    """Gmail SMTP adapter for repair result notifications."""

    def __init__(
        self,
        smtp_server: str | None = None,
        smtp_port: int | None = None,
        sender_email: str | None = None,
        sender_password: str | None = None,
        smtp_factory: Callable = smtplib.SMTP_SSL,
        drafting_llm=None,
    ):
        self.smtp_server = smtp_server or os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "465"))
        self.sender_email = sender_email or os.getenv("GOOGLE_EMAIL_ID", "")
        self.sender_password = sender_password or os.getenv("GOOGLE_APP_PASSWORD", "")
        self.smtp_factory = smtp_factory
        self.drafting_llm = drafting_llm

    def _draft_body(self, status: str, guid: str, summary: str, pr_url: str | None, diagnostics: str | None) -> str:
        fallback = [f"Repair status: {status}", f"GUID: {guid}", "", summary]
        if pr_url:
            fallback.extend(["", f"Pull request: {pr_url}"])
        if diagnostics:
            fallback.extend(["", "Diagnostics:", diagnostics])
        if os.getenv("ENABLE_GROQ_OPERATIONS_DRAFTING", "false").lower() != "true":
            return "\n".join(fallback)
        llm = self.drafting_llm or create_groq_model("operations")
        response = llm.invoke([
            ("system", "Draft a concise plain-text repair notification. Do not invent facts."),
            ("human", "\n".join(fallback)),
        ])
        content = getattr(response, "content", response)
        if not isinstance(content, str) or not content.strip():
            raise ToolError("Operations model returned an empty email draft.")
        return content.strip()

    @staticmethod
    def _validate_recipient(recipient: str) -> str:
        if "@" not in recipient:
            raise ToolError(f"Invalid recipient address: {recipient}")
        return recipient

    def send_repair_result(self, recipient: str, status: str, guid: str, summary: str, pr_url: str | None = None, diagnostics: str | None = None) -> dict:
        recipient = self._validate_recipient(recipient)
        if status not in {"fixed", "wontfix"}:
            raise ToolError(f"Unsupported repair status: {status}")
        if not guid:
            raise ToolError("GUID is required.")
        if not summary:
            raise ToolError("Summary is required.")
        if not self.sender_email or not self.sender_password:
            raise ToolError("GOOGLE_EMAIL_ID and GOOGLE_APP_PASSWORD are required.")

        subject = f"Night Shift repair {status}: {guid}"
        body = self._draft_body(status, guid, summary, pr_url, diagnostics)

        message = MIMEMultipart()
        message["From"] = self.sender_email
        message["To"] = recipient
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        try:
            with self.smtp_factory(self.smtp_server, self.smtp_port) as server:
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, [recipient], message.as_string())
        except (OSError, smtplib.SMTPException) as exc:
            raise ToolError(f"Email delivery failed: {exc}") from exc

        return {
            "recipient": recipient,
            "status": status,
            "guid": guid,
            "summary": summary,
            "pr_url": pr_url,
            "diagnostics": diagnostics,
            "sent": True,
        }


def build_email_tools(email: EmailMCP) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(MCPTool("send_repair_result", "Send a validated repair result to a recipient.", email.send_repair_result))
    return registry

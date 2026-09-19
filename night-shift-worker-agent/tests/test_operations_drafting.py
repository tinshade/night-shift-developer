import os
from email import message_from_string

from tools.email_mcp import EmailMCP
from tools.github_mcp import GitHubMCP


class FakeResponse:
    content = "Drafted operational summary."


class FakeLLM:
    def invoke(self, _messages):
        return FakeResponse()


class FakeSMTP:
    sent = None

    def __init__(self, *_args):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def login(self, *_args):
        pass

    def sendmail(self, *_args):
        self.sent = _args
        FakeSMTP.sent = _args


def test_operations_model_drafts_email(monkeypatch):
    monkeypatch.setenv("ENABLE_GROQ_OPERATIONS_DRAFTING", "true")
    email = EmailMCP(
        sender_email="sender@example.com",
        sender_password="password",
        smtp_factory=FakeSMTP,
        drafting_llm=FakeLLM(),
    )

    email.send_repair_result("developer@example.com", "fixed", "guid", "summary")

    sent_message = message_from_string(FakeSMTP.sent[2])
    assert sent_message.get_payload()[0].get_payload() == "Drafted operational summary."


def test_operations_model_drafts_pull_request(monkeypatch):
    monkeypatch.setenv("ENABLE_GROQ_OPERATIONS_DRAFTING", "true")
    github = GitHubMCP(drafting_llm=FakeLLM())

    assert github._pull_request_body("repair/guid") == "Drafted operational summary."
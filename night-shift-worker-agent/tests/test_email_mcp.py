from email import message_from_string

from tools.email_mcp import EmailMCP


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.logged_in = None
        self.sent = None
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def login(self, username, password):
        self.logged_in = (username, password)

    def sendmail(self, sender, recipients, content):
        self.sent = (sender, recipients, content)


def test_email_mcp_sends_repair_result_without_network():
    email = EmailMCP(
        sender_email="sender@example.com",
        sender_password="app-password",
        smtp_factory=FakeSMTP,
    )

    result = email.send_repair_result(
        recipient="developer@example.com",
        status="fixed",
        guid="guid-123",
        summary="Repair validated.",
        pr_url="https://github.com/example/repo/pull/1",
    )

    smtp = FakeSMTP.instances[-1]
    sent_message = message_from_string(smtp.sent[2])
    assert result["sent"] is True
    assert smtp.logged_in == ("sender@example.com", "app-password")
    assert smtp.sent[:2] == ("sender@example.com", ["developer@example.com"])
    assert sent_message["Subject"] == "Night Shift repair fixed: guid-123"
    assert "https://github.com/example/repo/pull/1" in sent_message.get_payload()[0].get_payload()
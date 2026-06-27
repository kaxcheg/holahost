import smtplib
from email.message import EmailMessage
from typing import ClassVar

import pytest
from pydantic import SecretStr

from application.exceptions import UpstreamEmailError
from domain.value_objects.email import Email
from domain.value_objects.magic_link import MagicLink
from infrastructure.email.smtp_email_sender import SmtpEmailSender


class _RecordingSMTP:
    sent: ClassVar[list[EmailMessage]] = []

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def __enter__(self) -> "_RecordingSMTP":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def send_message(self, message: EmailMessage) -> None:
        _RecordingSMTP.sent.append(message)


def _sender() -> SmtpEmailSender:
    return SmtpEmailSender(
        host="localhost",
        port=1025,
        from_address="dev@hola.host",
        magic_link_base_url="https://app.test/claim",
        magic_link_url_param="ml",
    )


def test_sends_message_with_html_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _RecordingSMTP.sent.clear()
    monkeypatch.setattr(smtplib, "SMTP", _RecordingSMTP)
    _sender().send_magic_link(Email("g@example.com"), MagicLink(SecretStr("tok9")))
    [msg] = _RecordingSMTP.sent
    assert msg["To"] == "g@example.com" and msg["From"] == "dev@hola.host"
    body = msg.get_body(("html",)).get_content()
    assert "https://app.test/claim/?ml=tok9" in body  # query form (B-43)
    assert "/claim/tok9" not in body  # old path form is gone


def test_smtp_failure_maps_to_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def __init__(self, *a: object) -> None:
            pass

        def __enter__(self) -> "_Boom":
            raise smtplib.SMTPException("down")

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(smtplib, "SMTP", _Boom)
    with pytest.raises(UpstreamEmailError):
        _sender().send_magic_link(Email("g@example.com"), MagicLink(SecretStr("t")))

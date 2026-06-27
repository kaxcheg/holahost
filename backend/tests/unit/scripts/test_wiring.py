import pytest

from infrastructure.email.resend_email_sender import ResendEmailSender
from infrastructure.email.smtp_email_sender import SmtpEmailSender
from scripts.wiring import check_embedder_ceiling, make_email_sender
from tests._support.fakes import FakeEmbeddingModel
from tests._support.settings import make_settings


def test_email_sender_dev_is_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "mailpit")
    monkeypatch.setenv("SMTP_PORT", "1025")
    assert isinstance(make_email_sender(make_settings(env="dev")), SmtpEmailSender)


def test_email_sender_prod_is_resend() -> None:
    sender = make_email_sender(make_settings(env="prod", database_url="postgresql://prod.db/app"))
    assert isinstance(sender, ResendEmailSender)


def test_ceiling_guard_raises() -> None:
    with pytest.raises(ValueError, match="max_chunk_tokens"):
        check_embedder_ceiling(
            make_settings(max_chunk_tokens=128, chunk_window=120),
            FakeEmbeddingModel(max_input_tokens=64),
        )


def test_ceiling_guard_passes_within_limit() -> None:
    check_embedder_ceiling(
        make_settings(max_chunk_tokens=128, chunk_window=120),
        FakeEmbeddingModel(max_input_tokens=128),
    )

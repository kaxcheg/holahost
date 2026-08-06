import pytest

from holahost_auth.config import AuthConfig


def test_rejects_empty_jwks_url() -> None:
    with pytest.raises(ValueError, match="jwks_url"):
        AuthConfig(
            jwks_url="",
            expected_algorithm="RS256",
            expected_issuer="auth",
            expected_audience="rag-documents",
            clock_skew_seconds=30,
        )


def test_rejects_negative_clock_skew() -> None:
    with pytest.raises(ValueError, match="clock_skew_seconds"):
        AuthConfig(
            jwks_url="https://auth.example/.well-known/jwks.json",
            expected_algorithm="RS256",
            expected_issuer="auth",
            expected_audience="rag-documents",
            clock_skew_seconds=-1,
        )

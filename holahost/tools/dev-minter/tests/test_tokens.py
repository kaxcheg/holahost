"""A minted token passes the platform's own validator, against the JWKS this package serves."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from holahost_auth.config import AuthConfig
from holahost_auth.context import TokenContext
from holahost_auth.exceptions import AuthenticationError
from holahost_auth.jwks import build_jwks_client
from holahost_auth.validator import authenticate

from dev_minter.keys import SigningKey, load_or_create
from dev_minter.server import JWKS_PATH, jwks_document, make_server
from dev_minter.tokens import GUEST_REPLY_CLI, ISSUER, Client, mint


@pytest.fixture
def key(tmp_path: Path) -> SigningKey:
    return load_or_create(tmp_path)


@pytest.fixture
def jwks_url(key: SigningKey) -> Iterator[str]:
    server = make_server(jwks_document(key), host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}{JWKS_PATH}"
    finally:
        server.shutdown()
        server.server_close()


def _validate(token: str, jwks_url: str, audience: str) -> TokenContext:
    """What a service's middleware does with the token, configured as its dev `.env.example` is."""
    config = AuthConfig(
        jwks_url=jwks_url,
        expected_algorithm="RS256",
        expected_issuer=ISSUER,
        expected_audience=audience,
        jwt_clock_skew_seconds=30,
    )
    return authenticate(f"Bearer {token}", config=config, jwks_client=build_jwks_client(jwks_url))


@pytest.mark.parametrize("audience", ["rag-documents", "llm-client"])
def test_a_guest_reply_token_passes_both_services(
    key: SigningKey, jwks_url: str, audience: str
) -> None:
    token = mint(key, GUEST_REPLY_CLI, now=datetime.now(UTC))
    context = _validate(token, jwks_url, audience)
    assert (context.subject, context.client_id) == ("guest-reply-cli", "guest-reply-cli")
    assert context.is_service_token


def test_a_token_for_another_audience_is_refused(key: SigningKey, jwks_url: str) -> None:
    token = mint(key, Client("pms-cli", ("pms-api",), 900), now=datetime.now(UTC))
    with pytest.raises(AuthenticationError):
        _validate(token, jwks_url, "rag-documents")


def test_an_expired_token_is_refused(key: SigningKey, jwks_url: str) -> None:
    token = mint(key, GUEST_REPLY_CLI, now=datetime.now(UTC) - timedelta(days=31))
    with pytest.raises(AuthenticationError):
        _validate(token, jwks_url, "rag-documents")


def test_the_lifetime_is_the_clients(key: SigningKey) -> None:
    now = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
    claims = jwt.decode(mint(key, GUEST_REPLY_CLI, now=now), options={"verify_signature": False})
    assert claims["iat"] == int(now.timestamp())
    assert claims["exp"] - claims["iat"] == 30 * 24 * 60 * 60


def test_a_month_old_token_still_passes(key: SigningKey, jwks_url: str) -> None:
    token = mint(key, GUEST_REPLY_CLI, now=datetime.now(UTC) - timedelta(days=29))
    assert _validate(token, jwks_url, "rag-documents").subject == "guest-reply-cli"


def test_every_token_is_unique(key: SigningKey) -> None:
    now = datetime.now(UTC)
    assert mint(key, GUEST_REPLY_CLI, now=now) != mint(key, GUEST_REPLY_CLI, now=now)


def test_the_header_names_the_key(key: SigningKey) -> None:
    header = jwt.get_unverified_header(mint(key, GUEST_REPLY_CLI, now=datetime.now(UTC)))
    assert header == {"alg": "RS256", "kid": key.kid, "typ": "JWT"}

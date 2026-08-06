import jwt
import pytest

from holahost_auth.jwks import build_jwks_client
from tests.conftest import JwksServerControl


def test_unknown_kid_triggers_single_refetch_then_succeeds(
    jwks_server: JwksServerControl,
) -> None:
    jwks_server("kid-1")
    client = build_jwks_client(jwks_server.url)
    client.get_signing_key("kid-1")  # populates the cache with kid-1 only

    jwks_server("kid-2")  # server rotates without the client knowing yet
    key = client.get_signing_key("kid-2")  # cache miss -> refetch once -> succeeds
    assert key.key_id == "kid-2"


def test_still_unknown_kid_after_refetch_raises(jwks_server: JwksServerControl) -> None:
    jwks_server("kid-1")
    client = build_jwks_client(jwks_server.url)

    with pytest.raises(jwt.PyJWKClientError):
        client.get_signing_key("nonexistent-kid")

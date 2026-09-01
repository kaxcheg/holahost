import time
from collections.abc import Callable
from typing import Any

import jwt as pyjwt
import pytest
from pytest_httpserver import HTTPServer

from holahost_auth.config import AuthConfig
from holahost_auth.exceptions import AuthenticationError, JwksUnavailableError
from holahost_auth.jwks import build_jwks_client
from holahost_auth.validator import authenticate


def test_service_token_context(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(
        kid="kid-1",
        claims={**base_claims, "sub": "chat-assistant-api", "client_id": "chat-assistant-api"},
    )
    ctx = authenticate(
        f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
    )
    assert ctx.is_service_token
    assert ctx.act is None


def test_user_token_context(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(
        kid="kid-1",
        claims={
            **base_claims,
            "sub": "user-123",
            "client_id": "web-guest-portal",
            "roles": ["guest"],
        },
    )
    ctx = authenticate(
        f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
    )
    assert not ctx.is_service_token
    assert ctx.roles == ("guest",)


def test_exchanged_token_context(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(
        kid="kid-1",
        claims={
            **base_claims,
            "sub": "user-123",
            "client_id": "chat-assistant-api",
            "act": {"sub": "chat-assistant-api"},
        },
    )
    ctx = authenticate(
        f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
    )
    assert ctx.act == "chat-assistant-api"


def test_missing_header_is_401(config: AuthConfig) -> None:
    with pytest.raises(AuthenticationError, match="missing"):
        authenticate(None, config=config, jwks_client=build_jwks_client(config.jwks_url))


def test_wrong_scheme_is_401(config: AuthConfig) -> None:
    with pytest.raises(AuthenticationError, match="Bearer"):
        authenticate("Basic abc", config=config, jwks_client=build_jwks_client(config.jwks_url))


def test_unparseable_token_is_401(config: AuthConfig) -> None:
    with pytest.raises(AuthenticationError):
        authenticate(
            "Bearer not-a-jwt", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_disallowed_alg_is_401(config: AuthConfig, base_claims: dict[str, Any]) -> None:
    # HS256 forged with an arbitrary shared secret, `kid` matching a real
    # registered key (alg-confusion attack shape: an attacker could try
    # reusing the public RSA key as an HMAC secret). The `kid` match means
    # this reaches the algorithm allowlist — without it, PyJWKClient would
    # reject the token earlier at kid-lookup ("no matching signing key"),
    # never actually exercising the alg check this test means to verify.
    token = pyjwt.encode(
        {**base_claims, "sub": "u", "client_id": "c"},
        "shared-secret",
        algorithm="HS256",
        headers={"kid": "kid-1"},
    )
    with pytest.raises(AuthenticationError):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_expired_token_is_401(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    expired = {**base_claims, "sub": "u", "client_id": "c", "exp": int(time.time()) - 3600}
    token = make_token(kid="kid-1", claims=expired)
    with pytest.raises(AuthenticationError):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_wrong_issuer_is_401(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(
        kid="kid-1", claims={**base_claims, "iss": "someone-else", "sub": "u", "client_id": "c"}
    )
    with pytest.raises(AuthenticationError):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_wrong_audience_is_401(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(
        kid="kid-1", claims={**base_claims, "aud": "someone-else", "sub": "u", "client_id": "c"}
    )
    with pytest.raises(AuthenticationError):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_unknown_kid_after_refetch_is_401(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(kid="nonexistent-kid", claims={**base_claims, "sub": "u", "client_id": "c"})
    with pytest.raises(AuthenticationError):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_jwks_connection_failure_raises_unavailable(
    make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    # Port 1 (tcpmux) is not listening on the test host: connection refused,
    # fast and reliable — no need to wait out a real timeout.
    unreachable = AuthConfig(
        jwks_url="http://127.0.0.1:1/jwks.json",
        expected_algorithm="RS256",
        expected_issuer="auth",
        expected_audience="rag-documents",
        jwt_clock_skew_seconds=30,
    )
    token = make_token(kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c"})
    with pytest.raises(JwksUnavailableError):
        authenticate(
            f"Bearer {token}",
            config=unreachable,
            jwks_client=build_jwks_client(unreachable.jwks_url),
        )


def test_jwks_malformed_response_raises_unavailable(
    httpserver: HTTPServer, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    httpserver.expect_request("/jwks.json").respond_with_data(
        "<html>not json</html>", content_type="text/html"
    )
    broken = AuthConfig(
        jwks_url=httpserver.url_for("/jwks.json"),
        expected_algorithm="RS256",
        expected_issuer="auth",
        expected_audience="rag-documents",
        jwt_clock_skew_seconds=30,
    )
    token = make_token(kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c"})
    with pytest.raises(JwksUnavailableError):
        authenticate(
            f"Bearer {token}", config=broken, jwks_client=build_jwks_client(broken.jwks_url)
        )


def test_malformed_act_missing_sub_is_401(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c", "act": {}})
    with pytest.raises(AuthenticationError, match="act"):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_malformed_act_not_a_dict_is_401(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(
        kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c", "act": "not-a-dict"}
    )
    with pytest.raises(AuthenticationError, match="act"):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )


def test_malformed_roles_is_401(
    config: AuthConfig, make_token: Callable[..., str], base_claims: dict[str, Any]
) -> None:
    token = make_token(
        kid="kid-1", claims={**base_claims, "sub": "u", "client_id": "c", "roles": "admin"}
    )
    with pytest.raises(AuthenticationError, match="roles"):
        authenticate(
            f"Bearer {token}", config=config, jwks_client=build_jwks_client(config.jwks_url)
        )

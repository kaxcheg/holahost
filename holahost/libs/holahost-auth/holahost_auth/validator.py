"""Core JWT validation: raw Authorization header -> TokenContext, offline."""

import json

import jwt

from holahost_auth.config import AuthConfig
from holahost_auth.context import TokenContext
from holahost_auth.exceptions import AuthenticationError, JwksUnavailableError


def authenticate(
    authorization_header: str | None,
    *,
    config: AuthConfig,
    jwks_client: jwt.PyJWKClient,
) -> TokenContext:
    """Validate a JWT from a raw `Authorization` header value, fully offline.

    Implements holahost_frame.md's validation procedure: scheme check, parse,
    `alg` pinning, signature by `kid`, standard claims, `TokenContext`. The
    only possible network call is the JWKS re-fetch inside `jwks_client`.

    :param authorization_header: Raw `Authorization` header value, or `None`.
    :param config: This service's fixed validation configuration.
    :param jwks_client: Configured `PyJWKClient` (see `jwks.build_jwks_client`).
    :raises AuthenticationError: on any per-request validation failure;
        `reason` is for logging, never for the HTTP response body.
    :raises JwksUnavailableError: the JWKS endpoint is unreachable or
        returned an unusable response — an infrastructure failure, not a
        statement about this particular token.
    """
    if authorization_header is None:
        raise AuthenticationError("missing Authorization header")

    scheme, _, token = authorization_header.partition(" ")
    if scheme != "Bearer" or not token:
        raise AuthenticationError("Authorization header is not a Bearer token")

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
    except jwt.PyJWKClientConnectionError as exc:
        raise JwksUnavailableError(f"JWKS endpoint unreachable: {exc}") from exc
    except json.JSONDecodeError as exc:
        # PyJWKClient.fetch_data() guards only URLError/TimeoutError, so a
        # non-JSON body (an HTML proxy error page) surfaces here. Same class
        # as a connection failure: the endpoint malfunctions, the token is
        # not at fault.
        raise JwksUnavailableError(f"JWKS endpoint returned invalid JSON: {exc}") from exc
    except (jwt.PyJWKClientError, jwt.InvalidTokenError) as exc:
        # PyJWKClient parses the header before the kid lookup, so a
        # structurally invalid token raises InvalidTokenError here.
        raise AuthenticationError(f"no matching JWKS signing key: {exc}") from exc

    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[config.expected_algorithm],
            issuer=config.expected_issuer,
            audience=config.expected_audience,
            leeway=config.jwt_clock_skew_seconds,
            options={"require": ["exp", "iat", "sub", "client_id"]},
        )
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError(f"token failed claim validation: {exc}") from exc

    return TokenContext(
        subject=claims["sub"],
        client_id=claims["client_id"],
        roles=_validated_roles(claims),
        act=_validated_act(claims),
    )


def _validated_roles(claims: dict[str, object]) -> tuple[str, ...]:
    """Extract and shape-check the optional `roles` claim.

    :raises AuthenticationError: `roles` is present but not a list of strings.
    """
    roles_claim = claims.get("roles", [])
    if not isinstance(roles_claim, list) or not all(isinstance(r, str) for r in roles_claim):
        raise AuthenticationError(f"malformed 'roles' claim: {roles_claim!r}")
    return tuple(roles_claim)


def _validated_act(claims: dict[str, object]) -> str | None:
    """Extract and shape-check the optional `act` claim (RFC 8693 delegation).

    Absent `act` means "not delegated" (`None`). A present but malformed one
    (not `{"sub": <non-empty str>}`) is rejected rather than read as "not
    delegated": failing open would let a tampered delegation marker past the
    confused-deputy check downstream (frame spec, point 6).

    :raises AuthenticationError: `act` is present but malformed.
    """
    act_claim = claims.get("act")
    if act_claim is None:
        return None
    if isinstance(act_claim, dict) and isinstance(act_claim.get("sub"), str) and act_claim["sub"]:
        subject: str = act_claim["sub"]
        return subject
    raise AuthenticationError(f"malformed 'act' claim: {act_claim!r}")

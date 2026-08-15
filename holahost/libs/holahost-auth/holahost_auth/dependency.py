"""FastAPI-native entry point: a configurable, Depends()-compatible callable."""

from fastapi import Header

from holahost_auth.config import AuthConfig
from holahost_auth.context import TokenContext
from holahost_auth.jwks import build_jwks_client
from holahost_auth.validator import authenticate


class HolahostAuth:
    """Configured, reusable FastAPI dependency for offline JWT validation.

    Instantiate once per service at the composition root — the JWKS client it
    holds is safe to reuse for the process's lifetime — and use as
    ``Depends(auth)`` on every router except health checks.

    :param config: This service's fixed validation configuration.
    """

    def __init__(self, config: AuthConfig) -> None:
        self._config = config
        self._jwks_client = build_jwks_client(config.jwks_url)

    def __call__(self, authorization: str | None = Header(default=None)) -> TokenContext:
        """FastAPI dependency callable.

        Raises ``authenticate()``'s own exception types directly — does not
        translate them to ``fastapi.HTTPException`` itself. Which HTTP status
        (and response shape) a given exception type maps to is the *consuming
        service's* interface-layer decision, not this library's: every other
        exception boundary in the platform follows the same rule (a port/
        library raises typed, protocol-agnostic exceptions; the interface
        layer owns type -> HTTP-status dispatch). The consuming service is
        expected to register its own exception handlers for both types (see
        this repo's own ``tests/test_dependency.py`` for a minimal example).

        :raises holahost_auth.exceptions.AuthenticationError: on any
            per-request validation failure; `reason` is for logging, never
            for the HTTP response body (US-R07).
        :raises holahost_auth.exceptions.JwksUnavailableError: the JWKS
            endpoint is unreachable or returned an unusable response — an
            infrastructure failure, not a statement about this particular
            token; the platform convention is to map this to 503, not 401,
            so it isn't reported to callers as "invalid credentials."
        """
        return authenticate(authorization, config=self._config, jwks_client=self._jwks_client)

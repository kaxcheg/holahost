"""FastAPI-native entry point: a configurable, Depends()-compatible callable."""

from fastapi import Header, HTTPException

from holahost_auth.config import AuthConfig
from holahost_auth.context import TokenContext
from holahost_auth.exceptions import AuthenticationError, JwksUnavailableError
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

        :raises fastapi.HTTPException: 401 on any `AuthenticationError` — the
            body carries no failure reason (US-R07); 503 on
            `JwksUnavailableError` — a JWKS outage rejects every token, so it
            must not look like "invalid credentials" to the caller. Both
            originals are chained via `from exc` so the service's own
            exception-logging middleware can still log the real reason.
        """
        try:
            return authenticate(authorization, config=self._config, jwks_client=self._jwks_client)
        except JwksUnavailableError as exc:
            raise HTTPException(status_code=503) from exc
        except AuthenticationError as exc:
            raise HTTPException(status_code=401) from exc

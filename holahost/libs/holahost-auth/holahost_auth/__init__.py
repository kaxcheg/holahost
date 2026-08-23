"""holahost-auth: offline JWT validation for Holahost services (ADR A-5)."""

from holahost_auth.config import AuthConfig
from holahost_auth.context import TokenContext
from holahost_auth.dependency import current_token
from holahost_auth.exceptions import AuthenticationError, JwksUnavailableError
from holahost_auth.middleware import TOKEN_SCOPE_KEY, HolahostAuthMiddleware

__all__ = [
    "TOKEN_SCOPE_KEY",
    "AuthConfig",
    "AuthenticationError",
    "HolahostAuthMiddleware",
    "JwksUnavailableError",
    "TokenContext",
    "current_token",
]

"""JWKS fetching and caching, configured to refresh only on an unknown `kid`."""

import jwt

# `lifespan` is a wall-clock TTL that would re-fetch regardless of whether the
# requested `kid` is known. Set beyond any realistic process uptime, so the only
# refresh trigger left is PyJWKClient's retry-once-on-unknown-kid.
_NO_TIME_BASED_EXPIRY_SECONDS = 10**9


def build_jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Build a `PyJWKClient` whose only refresh trigger is an unknown `kid`.

    :param jwks_url: URL of the JWKS endpoint.
    """
    return jwt.PyJWKClient(jwks_url, lifespan=_NO_TIME_BASED_EXPIRY_SECONDS)

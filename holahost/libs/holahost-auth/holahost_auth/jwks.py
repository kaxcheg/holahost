"""JWKS fetching and caching, configured to refresh only on an unknown `kid`."""

import jwt

# PyJWKClient's `lifespan` is a wall-clock TTL that would otherwise trigger a
# background re-fetch independent of whether the requested `kid` is known.
# rag-documents' documented cache lifecycle is "process lifetime, or an
# unknown kid" — no wall-clock expiry — so lifespan is set far beyond any
# realistic process uptime; the only refresh trigger left is PyJWKClient's
# own built-in retry-once-on-unknown-kid behavior.
_NO_TIME_BASED_EXPIRY_SECONDS = 10**9


def build_jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """Build a `PyJWKClient` whose only refresh trigger is an unknown `kid`.

    :param jwks_url: URL of the JWKS endpoint.
    """
    return jwt.PyJWKClient(jwks_url, lifespan=_NO_TIME_BASED_EXPIRY_SECONDS)

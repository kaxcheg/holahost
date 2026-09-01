"""The bearer-token declaration a service attaches to its guarded routers.

It **declares, never enforces**: ``HolahostAuthMiddleware`` has answered long before any
dependency runs. ``auto_error=False`` is what keeps it a declaration — left at ``True`` it
becomes a second gate, standing behind the one that already answered, in a different order
and with a body of its own. What it buys is the only thing FastAPI's schema generator
cannot learn from middleware: that these routes take a bearer token.

``X-Request-ID`` is required just as strictly of a guarded route and deliberately has no
equivalent here. It is not the caller's to send — every intended entry path attaches it —
and publishing it would undo ``MalformedRequestError``'s muteness by naming the header to
the one caller who could be missing it.
"""

from __future__ import annotations

from fastapi.security import HTTPBearer

BEARER_SCHEME_NAME = "bearerAuth"
"""The component name in the generated document. Fixed across services so a consumer
integrating with two of them sees one scheme, not two spellings of it."""


def bearer_scheme(description: str) -> HTTPBearer:
    """Build the declaration to pass as ``dependencies=[Security(...)]`` on a router.

    Args:
        description: What the token means *to this service* — which claim it scopes
            resources by, and how it answers a subject that has none. The mechanics are
            the platform's and identical everywhere; this sentence is not.
    """
    return HTTPBearer(
        scheme_name=BEARER_SCHEME_NAME,
        bearerFormat="JWT",
        auto_error=False,
        description=description,
    )

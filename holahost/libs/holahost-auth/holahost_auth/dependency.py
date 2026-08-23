"""FastAPI-native entry point: typed access to the already-validated token."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from holahost_auth.context import TokenContext
from holahost_auth.middleware import TOKEN_SCOPE_KEY


def current_token(request: Request) -> TokenContext:
    """FastAPI dependency returning the caller's validated ``TokenContext``.

    Reads what ``HolahostAuthMiddleware`` put in the request scope; it does not
    validate anything itself. Validation happens once, before routing, because it has
    to: a dependency runs after the framework has already read the request body, so
    authenticating there means every anonymous upload is received in full first.

    That leaves this as the typed handle on the result — annotate a route parameter
    ``Annotated[TokenContext, Depends(current_token)]`` and get the context, with none
    of the "did auth actually run for this route?" ambiguity a second validation path
    would reintroduce.

    :raises RuntimeError: the route is not covered by ``HolahostAuthMiddleware`` (or
        is listed among its ``public_paths``). A wiring mistake, not a caller error —
        it must not be answered with 401, which would report a service defect as bad
        credentials.
    """
    token = request.scope.get("state", {}).get(TOKEN_SCOPE_KEY)
    if token is None:
        raise RuntimeError(
            f"no validated token for {request.method} {request.url.path} — the route "
            f"depends on current_token but HolahostAuthMiddleware did not authenticate "
            f"it (missing from the middleware stack, or listed in public_paths)"
        )
    # cast rather than isinstance: the middleware above is the only writer of this key,
    # and an assert would be stripped under `-O` exactly where it was meant to hold.
    return cast(TokenContext, token)

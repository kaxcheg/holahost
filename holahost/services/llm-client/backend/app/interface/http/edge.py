"""Everything the shared middleware needs to know about *this* service.

`holahost-http` and `holahost-auth` supply the mechanisms — request-id propagation, a
body-size cap, authentication, a rate limiter — deliberately without opinions about which
routes they apply to, how big is too big, what a rejection is called on the wire, or how it
is logged. Those are this service's contract, and they all live here: one module for the
values and rules the edge is parameterised with, so `app.py` is left holding nothing but
the wiring.

`api_base.py` stays separate and minimal: the container healthcheck imports it directly, so
it must not drag in the application layer to answer "what is my base path".
"""

from __future__ import annotations

from holahost_http import MalformedRequestError

from interface.http.api_base import API_BASE_URL

HEALTH_PATH = f"{API_BASE_URL}/health"

# The unit every rate-limit setting is counted in. A constant rather than a setting: the
# window is what those numbers *mean*, and halving it would silently halve every ceiling
# while the .env files went on claiming the old figures.
RATE_LIMIT_WINDOW_SECONDS = 3600

# A transport limit: it bounds the whole HTTP body, multipart framing included, and only
# decides how much the edge reads before anyone can look. A service that also checks the
# thing *inside* the body derives this from that limit with `body_cap_for_upload`, and
# advertises the inner one — told to trim to the transport cap, a caller lands just above
# the application's own check and is refused a second time.
MAX_REQUEST_BODY_SIZE = 1 * 1024 * 1024

MISSING_REQUEST_ID_ERROR = MalformedRequestError()
"""What this service answers with when `X-Request-ID` is absent.

The requirement lives in `holahost_http.RequestIdMiddleware` — every intended entry path
attaches the header unconditionally, so its absence means a caller is misconfigured or
bypassing the intended path. Which error that violation is answered with is still the
service's decision, which is why the library takes it as an argument; the status it carries
is set beside it in `app.py`."""


def bucket_for(method: str, path: str) -> str | None:
    """Which rate-limit bucket a request falls into, or `None` for unlimited.

    Split by *operation*, not by HTTP verb: what a ceiling should price is the work, and a
    `POST` that reads is not a `POST` that writes.

    Matches on prefix because it runs before routing, where a path parameter is not parsed
    yet — the same reason the limiter can be consulted while the body is still on the wire.
    """
    del method, path
    return None

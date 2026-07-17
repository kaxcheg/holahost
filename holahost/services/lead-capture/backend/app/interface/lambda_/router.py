"""Route a Lambda Function URL event to its use case (spec §8.5 / §8.7).

``dispatch`` maps ``(method, rawPath)`` to a request parser + the Container attribute holding the
use case, returning ``(cmd, use_case)`` for the handler to execute. Unknown routes raise
``NotFoundError`` (→ 404).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from application.exceptions import NotFoundError
from interface.lambda_ import request_parsing as rp

if TYPE_CHECKING:
    from config.config import Settings

# (method, sub-path) → (event→Cmd parser, Container use-case attribute name) (§8.7). Routes are
# service-relative — the mount prefix (Settings.api_base_url, e.g. /api/lead-capture) is stripped in
# ``dispatch``, so API_BASE_URL is the single source of the prefix (§11.6).
_ROUTES: dict[tuple[str, str], tuple[Callable[[dict[str, Any], Settings], Any], str]] = {
    ("POST", "/sample/generate"): (rp.parse_sample_generate, "sample_generate"),
    ("POST", "/leads/capture"): (rp.parse_capture_lead, "capture_lead"),
    ("GET", "/magic-link/resolve"): (rp.parse_resolve_magic_link, "resolve_magic_link"),
    ("POST", "/ingest/upload"): (rp.parse_upload_guidebook, "upload_guidebook"),
    ("POST", "/generate"): (rp.parse_generate_response, "generate_response"),
}


def dispatch(event: dict[str, Any], container: Any) -> tuple[Any, Any]:
    """Resolve the event to ``(cmd, use_case)``.

    :raises NotFoundError: if no route matches ``(method, rawPath)`` (→ 404).
    """
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    # Strip the config-driven mount prefix (Settings.api_base_url) so routes stay service-relative.
    subpath = path.removeprefix(container.settings.api_base_url)
    route = _ROUTES.get((method, subpath))
    if route is None:
        raise NotFoundError(resource="endpoint", message=f"no route for {method} {path}")
    parse_fn, attr = route
    cmd = parse_fn(event, container.settings)
    return cmd, getattr(container, attr)

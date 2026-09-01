"""The service's own name, and the one public path segment derived from it.

The frame spec makes `<svc>` a single identity with three derived uses: the container name
on the `backbone` network, the ECR repository name, and this path segment —
`API_BASE_URL = /api/<svc>`, a bare path with no domain, because the gateway routes by path
and does not rewrite it.

Derived here rather than spelled out at each mount point, and the derivation is the point:
the segment is not an independent choice a router gets to make, it is the service's name.
Written out per router instead, it drifts — and a health route published outside the base
path is reachable from inside the compose network only, so the deploy's smoke check never
reaches it.

Not a `Settings` field despite the ALL-CAPS name: it is derived from an identity that is
fixed for the service, so there is nothing per-environment to configure — and an
env-configurable base path is a value staging and prod could silently disagree on, taking
every route to 404 at once.

Kept free of imports: the container's HEALTHCHECK reads it directly, and must not drag in
the application layer to answer "what is my base path".
"""

from __future__ import annotations

SERVICE_NAME = "<svc>"
API_BASE_URL = f"/api/{SERVICE_NAME}"

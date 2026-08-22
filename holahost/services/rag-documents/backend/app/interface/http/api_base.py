"""The service's own name, and the one public path segment derived from it.

The frame spec (`holahost/docs/holahost_frame.md`, "Задание на разработку инфраструктуры и
CI/CD микросервиса") makes `<svc>` a single identity with three derived uses: the container
name on the `backbone` network, the ECR repository name, and this path segment —
`API_BASE_URL = /api/<svc>`, a bare path with no domain, because the platform gateway routes
by path and does not rewrite it.

Derived here rather than spelled out at each mount point, and the derivation is the point: the
segment is not an independent choice a router gets to make, it is the service's name. Written
out per router instead, it had already drifted — the documents router carried the full literal
while `health` carried none at all, which put `GET /api/rag-documents/health` (the path both
deploy pipelines smoke-check, per the frame spec's own "Smoke: `curl
https://<domain>/api/<svc>/health`") on no route at all.

Not a `Settings` field despite the ALL-CAPS name: this is derived from the service's identity,
which is fixed for the service, so there is nothing per-environment to configure — and an
env-configurable base path is a value staging and prod could silently disagree on, taking every
route in the service to 404 at once.
"""

from __future__ import annotations

SERVICE_NAME = "rag-documents"
API_BASE_URL = f"/api/{SERVICE_NAME}"

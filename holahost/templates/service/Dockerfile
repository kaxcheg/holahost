# syntax=docker/dockerfile:1
# Build context MUST be the TRUE git repo root (parent of holahost/), not holahost/ itself and not
# this directory: .tool-versions lives at the true root (single source for local dev/Docker/CI —
# confirmed by build failure when context was holahost/, .tool-versions not found there), while
# backend/pyproject.toml's Poetry path dependency on ../../../libs/holahost-auth requires
# holahost/libs/holahost-auth/ to also be reachable. Both are only simultaneously reachable from
# the true root. Build (from the true repo root, i.e. two levels above holahost/services/):
#   docker build -f holahost/services/<svc>/Dockerfile \
#     --build-arg PYTHON_VERSION=$(awk '$1=="python"{print $2}' .tool-versions) -t <svc>:dev .
#
# PYTHON_VERSION has no default on purpose: it's what FROM below resolves to, before any RUN/COPY
# runs — Docker can't awk .tool-versions for it the way the poetry install below does (that trick
# only works once a shell exists, inside an already-pulled stage). A default here would silently
# drift from .tool-versions the moment that file changes, which is exactly the bug this replaced —
# every real caller (make, CI) already passes --build-arg explicitly; a bare `docker build` without
# it now fails loudly instead of quietly building a stale Python version.
ARG PYTHON_VERSION

FROM python:${PYTHON_VERSION}-slim AS builder
# Same root name as the runtime stage below, deliberately — not /build: holahost-auth's editable
# install (see the comment at its COPY below) bakes whatever absolute path it's installed FROM
# into a .pth file, which then gets copied byte-for-byte into the runtime stage's venv. If this
# stage used a different root, that literal path (/build/...) would leak into the shipped runtime
# image as a directory that has to exist there too, despite meaning nothing at runtime — a real
# stray artifact, not just a naming mismatch. Using /app in both stages means the .pth already
# points where the runtime stage puts everything else, so nothing extra has to exist.
WORKDIR /app
COPY .tool-versions ./
RUN pip install --no-cache-dir "poetry==$(awk '$1=="poetry"{print $2}' .tool-versions)" \
 && poetry config virtualenvs.in-project true
# Copied at the SAME nested depth as on disk (../../../libs/holahost-* is relative to
# backend/pyproject.toml's own location) so the Poetry path dependencies resolve inside the
# image. Both libraries, and holahost-auth's own path dependency on holahost-http means the
# latter has to be here even for the former to install.
COPY holahost/libs/ /app/holahost/libs/
COPY holahost/services/<svc>/backend/pyproject.toml holahost/services/<svc>/backend/poetry.lock \
     /app/holahost/services/<svc>/backend/
WORKDIR /app/holahost/services/<svc>/backend
RUN poetry install --only main --no-interaction --no-ansi --no-root

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/holahost/services/<svc>/backend/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
# Both libs are Poetry `develop = true` path dependencies: installed editable, so
# site-packages/holahost_{auth,http}.pth point at the literal builder-stage paths
# (/app/holahost/libs/..., same root as this stage — see the builder stage's own comment
# above) instead of vendoring the modules — those paths must exist here too, at the exact
# same locations, or the imports fail at runtime.
COPY holahost/libs/ /app/holahost/libs/
COPY holahost/services/<svc>/backend/app/ /app/
COPY holahost/services/<svc>/backend/migrations/ /app/migrations/
COPY holahost/services/<svc>/backend/alembic.ini /app/alembic.ini

# The path comes from `interface.http.api_base`, the same module `create_app()` mounts every
# router under — not a third hand-written copy of the literal. A bare `/health` was written here
# once and silently became a 404 the moment routers moved under the service's base path, leaving
# the container permanently `unhealthy` (urlopen raises HTTPError on 404, so the probe exits
# non-zero on every attempt) while the service itself was answering fine.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "from interface.http.api_base import API_BASE_URL; import urllib.request as u; u.urlopen(f'http://localhost:8080{API_BASE_URL}/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "scripts.bootstrap:app", "--host", "0.0.0.0", "--port", "8080"]

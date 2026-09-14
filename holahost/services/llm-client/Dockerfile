# syntax=docker/dockerfile:1
# The build context MUST be the git repo root (the parent of holahost/), not holahost/ itself and
# not this directory: `.tool-versions` lives at that root and is the single source of tool versions
# for local dev, Docker and CI, while backend/pyproject.toml's Poetry path dependency on
# ../../../libs/holahost-auth needs holahost/libs/ reachable too. Only the repo root reaches both.
# Build from there:
#   docker build -f holahost/services/llm-client/Dockerfile \
#     --build-arg PYTHON_VERSION=$(awk '$1=="python"{print $2}' .tool-versions) -t llm-client:dev .
#
# PYTHON_VERSION has no default on purpose: it is what FROM below resolves to, before any RUN or
# COPY runs, so Docker cannot read it out of .tool-versions the way the poetry install below does —
# that only works once a shell exists inside an already-pulled stage. A default here would drift
# from .tool-versions the moment that file changes. Every real caller (make, CI) passes
# --build-arg explicitly, and a bare `docker build` without it fails loudly instead of quietly
# building a stale Python version.
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
COPY holahost/services/llm-client/backend/pyproject.toml holahost/services/llm-client/backend/poetry.lock \
     /app/holahost/services/llm-client/backend/
WORKDIR /app/holahost/services/llm-client/backend
RUN poetry install --only main --no-interaction --no-ansi --no-root

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/holahost/services/llm-client/backend/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
# Both libs are Poetry `develop = true` path dependencies: installed editable, so
# site-packages/holahost_{auth,http}.pth point at the literal builder-stage paths
# (/app/holahost/libs/..., same root as this stage — see the builder stage's own comment
# above) instead of vendoring the modules — those paths must exist here too, at the exact
# same locations, or the imports fail at runtime.
COPY holahost/libs/ /app/holahost/libs/
COPY holahost/services/llm-client/backend/app/ /app/
COPY holahost/services/llm-client/backend/migrations/ /app/migrations/
COPY holahost/services/llm-client/backend/alembic.ini /app/alembic.ini

# The path comes from `interface.http.api_base`, the same module `create_app()` mounts every
# router under, rather than a third hand-written copy of the literal. A bare `/health` here would
# be a 404, leaving the container permanently `unhealthy` — urlopen raises HTTPError on 404, so
# the probe exits non-zero on every attempt — while the service itself answers fine.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "from interface.http.api_base import API_BASE_URL; import urllib.request as u; u.urlopen(f'http://localhost:8080{API_BASE_URL}/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "scripts.bootstrap:app", "--host", "0.0.0.0", "--port", "8080"]

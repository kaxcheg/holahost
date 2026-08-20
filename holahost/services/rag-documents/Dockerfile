# syntax=docker/dockerfile:1
# Build context MUST be the TRUE git repo root (parent of holahost/), not holahost/ itself and not
# this directory: .tool-versions lives at the true root (single source for local dev/Docker/CI —
# confirmed by build failure when context was holahost/, .tool-versions not found there), while
# backend/pyproject.toml's Poetry path dependency on ../../../libs/holahost-auth requires
# holahost/libs/holahost-auth/ to also be reachable. Both are only simultaneously reachable from
# the true root. Build (from the true repo root, i.e. two levels above holahost/services/):
#   docker build -f holahost/services/rag-documents/Dockerfile \
#     --build-arg PYTHON_VERSION=$(awk '$1=="python"{print $2}' .tool-versions) -t rag-documents:dev .
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
# Copied at the SAME nested depth as on disk (../../../libs/holahost-auth is relative to
# backend/pyproject.toml's own location) so the Poetry path dependency resolves inside the image.
COPY holahost/libs/holahost-auth/ /app/holahost/libs/holahost-auth/
COPY holahost/services/rag-documents/backend/pyproject.toml holahost/services/rag-documents/backend/poetry.lock \
     /app/holahost/services/rag-documents/backend/
WORKDIR /app/holahost/services/rag-documents/backend
RUN poetry install --only main --no-interaction --no-ansi --no-root

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /app/holahost/services/rag-documents/backend/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
# holahost-auth is a Poetry `develop = true` path dependency: it's installed editable, so
# site-packages/holahost_auth.pth points at the literal builder-stage path
# (/app/holahost/libs/holahost-auth, same root as this stage — see the builder stage's own
# comment above) instead of vendoring the module — that path must exist here too, at the exact
# same location, or the import fails at runtime.
COPY holahost/libs/holahost-auth/ /app/holahost/libs/holahost-auth/
COPY holahost/services/rag-documents/backend/app/ /app/
COPY holahost/services/rag-documents/backend/migrations/ /app/migrations/
COPY holahost/services/rag-documents/backend/alembic.ini /app/alembic.ini

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8080/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "scripts.bootstrap:app", "--host", "0.0.0.0", "--port", "8080"]

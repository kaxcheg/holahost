# Shared backend image: local dev (Lambda RIE) + reused by C-06 deploy. The AWS Lambda Python 3.12 base
# bundles the Runtime Interface Client and, for local use, the Runtime Interface Emulator.
# Build CONTEXT = the repo ROOT (the Dockerfile reads /.tool-versions); paths below are repo-relative and
# trimmed by /.dockerignore. Build: `docker build -f holahost/services/lead-capture/backend/Dockerfile .`
# Tool versions are single-sourced from /.tool-versions (also used by mise/asdf locally): PYTHON_VERSION
# defaults below (override via --build-arg from CI); the poetry version is read from the file in the RUN.
ARG PYTHON_VERSION=3.12
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION}

# Bake the embedding model into the image so cold start is warm (§2.1). fastembed reads this same var at
# runtime (common/utils.py: os.getenv("FASTEMBED_CACHE_PATH", ...)), so the preloaded model is reused.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed

# Install main (non-dev) deps from the lockfile into system site-packages — no venv. The poetry version is
# read from /.tool-versions (single source); the deps themselves are pinned by poetry.lock.
COPY .tool-versions holahost/services/lead-capture/backend/pyproject.toml holahost/services/lead-capture/backend/poetry.lock ./
RUN POETRY_VERSION="$(awk '$1=="poetry"{print $2}' .tool-versions)" \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
 && poetry config virtualenvs.create false \
 && poetry install --only main --no-interaction --no-ansi

# Application code → LAMBDA_TASK_ROOT; app/ contents become the import root (pythonpath = app).
COPY holahost/services/lead-capture/backend/app/ ${LAMBDA_TASK_ROOT}/

# NOTE: docs/sample_guidebook.md (business content, read at cold start by wiring.build()) is NOT baked —
# it must be editable without a redeploy. Dev mounts it (docker-compose); prod reads it from S3 (future
# ticket: externalize SAMPLE_GUIDEBOOK_PATH to an S3 object loaded at cold start).

# Preload the embedding model at BUILD time so it is baked into the image — this makes the RUNTIME cold
# start warm (no model download on first invocation, §2.1). It deliberately spends build time to save
# runtime latency. The model name is a build ARG (default = the spec model); the runtime
# EMBEDDING_MODEL_NAME must match it, otherwise the model re-downloads on first use.
ARG EMBEDDING_MODEL_NAME=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='$EMBEDDING_MODEL_NAME')"

# Request Lambda handler (spec §8.5/§8.6). Cleanup Lambda overrides CMD to scripts.bootstrap_cleanup.lambda_handler.
CMD ["interface.lambda_.handler.lambda_handler"]

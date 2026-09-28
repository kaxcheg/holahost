# syntax=docker/dockerfile:1
# Build context: this directory. `make dev-up` builds it:
#   docker build --build-arg PYTHON_VERSION=<from .tool-versions> -t dev-minter:dev .
#
# PYTHON_VERSION has no default, as in the services' images: a default would drift from
# .tool-versions, the one source of the version, and a bare build fails loudly instead.
ARG PYTHON_VERSION

FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /opt/dev-minter
# Built from pyproject.toml's ranges rather than the lock: the image is dev-only, never deployed,
# and one dependency deep. The lock is what the tests run against.
COPY pyproject.toml ./
COPY dev_minter/ ./dev_minter/
RUN pip install --no-cache-dir .

# An unprivileged owner for the key. Docker seeds an empty named volume from the image's directory,
# ownership included, so the volume mounted here is writable by this user alone.
RUN useradd --system --no-create-home minter \
 && mkdir -p /var/lib/dev-minter \
 && chown minter /var/lib/dev-minter \
 && chmod 700 /var/lib/dev-minter
USER minter

EXPOSE 8081
CMD ["python", "-m", "dev_minter", "serve"]

# Make targets every Holahost service shares.
#
# A service's own Makefile sets the handful of variables below and includes this file:
#
#     SVC := rag-documents
#     MAX_IMAGE_MB := 900
#     include ../../make/common.mk
#
# and then adds only what is genuinely its own. Everything here is derived from `SVC`: that one
# name is already the container name on `backbone`, the ECR repository, the path segment and the
# secret prefix, so a second source for any of them is a second thing to keep in step.
#
# The targets live here rather than in each service because the interesting part is not the
# commands but the ordering and the quoting: `migrate` before `up`, the bare `pre-commit`, the
# twice-set superuser password, the quoting at each point of use. Each is commented where it
# happens.

REPO_ROOT ?= ../../..
BE ?= backend
DEV_ENV_FILE ?= infra/envs/dev/.env

# Single source of truth for the image's Python version, same as the Dockerfile and CI use.
# Read by the two targets that build an image and by nothing else. Not exported: GNU Make
# exports only variables that came from its own environment or the command line, never ones
# defined here, so a `docker compose` child still sees it unset — which is what
# docker-compose.yml expects.
PYTHON_VERSION := $(shell awk '$$1=="python"{print $$2}' $(REPO_ROOT)/.tool-versions)

DEV_IMAGE ?= $(SVC):dev
CI_IMAGE ?= $(SVC):ci
MAX_IMAGE_MB ?= 900

# One prefix instead of repeating four parts on six recipes. `-f docker-compose.dev.yml` is
# the dev-only overlay that publishes the app port to the host — it is never synced to an
# instance, which is what keeps 0.0.0.0:8080 off staging and prod. `--env-file` supplies
# Compose's own `$${VAR}` interpolation from the same file the containers read.
#
# IMAGE is the only value passed inline, because it is the only one not in that file.
DEV_COMPOSE ?= IMAGE=$(DEV_IMAGE) \
               docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file $(DEV_ENV_FILE)

.DEFAULT_GOAL := help
.PHONY: help lint format typecheck test test-int lint-imports openapi openapi-check \
        dev-up dev-down dev-down-v dev-logs migrate-dev migrate-staging migrate-prod \
        hooks-install ci-local ci-image ci-tf

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-20s\033[0m %s\n",$$1,$$2}'

# ---- Static analysis and tests -------------------------------------------------------

lint: ## ruff check
	cd $(BE) && poetry run ruff check app tests
format: ## ruff format
	cd $(BE) && poetry run ruff format app tests
typecheck: ## mypy strict, whole package
	cd $(BE) && poetry run mypy .
test: ## unit tests (no Docker)
	cd $(BE) && poetry run pytest -m "not integration"
test-int: ## integration tests (testcontainers; needs Docker)
	cd $(BE) && poetry run pytest -m integration
lint-imports: ## clean-architecture import contract
	cd $(BE) && poetry run lint-imports

# ---- The published contract ----------------------------------------------------------

openapi: ## regenerate docs/openapi.json from the code
	cd $(BE) && poetry run python -m scripts.dump_openapi

openapi-check: ## fail if docs/openapi.json is stale (CI parity)
	cd $(BE) && poetry run python -m scripts.dump_openapi --check

# ---- Local stack ---------------------------------------------------------------------

# Explicit `docker build`, not `docker compose up --build`: docker-compose.yml carries no
# `build:` section, so this is the only place anything is built for dev, in the same shape
# CI's `build-push-image` action uses.
#
# `migrate-dev` BEFORE `up -d`, the same order the deploy uses (migrations, then role
# provisioning, then the container swap). The other way round is not merely inconsistent:
# on a fresh volume `up -d` starts the app before its role exists, so the container fails
# to authenticate and sits in a restart loop — while `dev-up` itself exits 0, reporting
# success over a stack that cannot serve a request.
#
# No `up -d postgres` first: `migrate-dev`'s `docker compose run api` creates the network
# and volumes, starts `postgres` and waits for it to become healthy on its own, through the
# `api` service's `depends_on: condition: service_healthy`.
dev-up: ## build, migrate, then start the local stack (creates the backbone network if missing)
	docker network create backbone 2>/dev/null || true
	docker build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -f Dockerfile -t $(DEV_IMAGE) $(REPO_ROOT)
	$(MAKE) migrate-dev
	$(DEV_COMPOSE) up -d
dev-down: ## stop the dev stack
	$(DEV_COMPOSE) down
dev-down-v: ## stop + wipe volumes (fresh DB and caches)
	$(DEV_COMPOSE) down -v
dev-logs: ## follow stack logs
	$(DEV_COMPOSE) logs -f

# ---- Migrations ----------------------------------------------------------------------

# `python -m`, not the bare console script: its shebang breaks once relocated into the
# runtime image — same fix as the Dockerfile's CMD.
#
# Both steps override the container's CMD (bypassing the composition root) and both are
# ELEVATED: `migrations/env.py` and `scripts/provision_app_role.py` each build their DSN
# from POSTGRES_SUPERUSER/POSTGRES_SUPERUSER_PASSWORD, not the app's own credentials —
# creating extensions and policies is superuser/owner-only, and the app role must hold
# neither privilege.
#
# Two steps, always in this order: `upgrade head` creates the tables as the superuser that
# owns them, then provisioning grants the app role plain DML on whatever now exists — so a
# migration that adds a table is covered by the same run that creates it. Provisioning is
# also what applies a rotated `db-password`: nothing else in the stack changes the role's
# password, so a rotation takes effect on the next deploy, not on a bare restart.
migrate-dev: ## alembic upgrade head + provision the app role, against the compose Postgres
	$(DEV_COMPOSE) run --rm api python -m alembic upgrade head
	$(DEV_COMPOSE) run --rm api python -m scripts.provision_app_role

# The pipelines invoke these commands inline via SSM Run Command, not these targets — they
# exist for an operator to reproduce the same migration by hand on the instance, where
# there is a deployed container rather than a poetry-managed checkout and where the AWS
# credentials for the `aws secretsmanager` calls come from the instance role.
#
# Requires IMAGE=<repo>@<digest>. Deliberately no `IMAGE=$(DEV_IMAGE)` prefix, unlike the
# dev targets: GNU Make auto-exports a variable set on the command line, so an explicit
# prefix is redundant when IMAGE *is* passed — and its absence closes a real gap, because
# a forgotten IMAGE then hits `docker compose`'s own `$${IMAGE:?...}` check instead of
# silently substituting a dev tag against a real database.
#
# POSTGRES_SUPERUSER_PASSWORD is set twice per line on purpose: once as a shell prefix,
# feeding Compose's own interpolation of the `postgres` service's block, and once through
# `docker compose run -e`, because the `api` service has only `env_file:` and both
# invocations override the container's CMD, bypassing its own Secrets Manager fetch.
#
# Every value is quoted at its point of use: unquoted, a generated password containing a
# space splits into two `docker compose` arguments, and one containing `*` or `?` globs
# against the working directory and hands the container a different string than the secret
# holds. The `VAR=$$PW` assignment prefix is exempt by shell rules, so quoting it too is
# redundant — and consistent, which is what keeps the exposed forms from being overlooked.
define migrate_remote
	PGPW=$$(aws secretsmanager get-secret-value --secret-id holahost/$(1)/$(SVC)/db-password --query SecretString --output text); \
	SUPERPW=$$(aws secretsmanager get-secret-value --secret-id holahost/$(1)/$(SVC)/db-superuser-password --query SecretString --output text); \
	cd /opt/services/$(SVC) && \
	POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW docker compose --env-file infra/envs/$(1)/.env run --rm -e "POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW" api python -m alembic upgrade head && \
	POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW docker compose --env-file infra/envs/$(1)/.env run --rm -e "POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW" -e "POSTGRES_PASSWORD=$$PGPW" api python -m scripts.provision_app_role
endef

migrate-staging: ## run by deploy-staging via SSM; manual use: make migrate-staging IMAGE=<repo>@<digest>
	$(call migrate_remote,staging)
migrate-prod: ## run by promote-prod via SSM; manual use: make migrate-prod IMAGE=<repo>@<digest>
	$(call migrate_remote,prod)

# ---- CI parity -----------------------------------------------------------------------

# Bare `pre-commit`, NOT `poetry run pre-commit` from inside the backend: the repo-root
# config's hooks auto-discover and `cd`+`poetry run` into EVERY package, and running the
# outer tool through this package's own venv leaks its VIRTUAL_ENV into those subprocesses,
# breaking poetry's venv resolution for every *other* package's hook run. Must run from the
# true repo root — the hooks' paths and discovery are repo-root-relative.
hooks-install: ## install git hooks (repo-root pre-commit config)
	cd $(REPO_ROOT) && pre-commit install

# Three targets, not one, and the split is what keeps the parity claim honest. `ci-local` covers
# everything that needs no Docker and no cloud credentials — including `openapi-check`, which is
# what catches a renamed route or a response field that quietly became optional. `ci-image` and
# `ci-tf` each add one dependency. Deliberately not covered anywhere: `terraform plan`, which
# needs real credentials and is gated in CI for that reason.
ci-local: ## pre-commit + the full test suite + the OpenAPI contract check (no Docker/Terraform)
	cd $(REPO_ROOT) && pre-commit run --all-files
	cd $(BE) && poetry run pytest
	$(MAKE) openapi-check
ci-image: ## the CI checks that need Docker: build the image, then the size budget
	docker build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -f Dockerfile -t $(CI_IMAGE) $(REPO_ROOT)
	@size_mb=$$(( $$(docker image inspect $(CI_IMAGE) --format '{{.Size}}') / 1000000 )); \
	echo "$(CI_IMAGE) is $${size_mb} MB (ceiling $(MAX_IMAGE_MB) MB)"; \
	if [ "$$size_mb" -gt "$(MAX_IMAGE_MB)" ]; then \
		echo "image grew past its budget — check .dockerignore and new dependencies"; \
		exit 1; \
	fi
# `-backend=false`: validate needs no state and no credentials, which is exactly why CI can
# run it on a fork PR. It cannot see drift, though — `terraform plan` is what catches that,
# and the two are a pair rather than alternatives.
ci-tf: ## the CI checks that need Terraform: validate common + both env roots
	cd infra/common && terraform init -backend=false && terraform validate
	cd infra/envs/staging && terraform init -backend=false && terraform validate
	cd infra/envs/prod && terraform init -backend=false && terraform validate

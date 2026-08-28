.DEFAULT_GOAL := help
.PHONY: help lint format typecheck test test-int lint-imports \
        dev-up dev-down dev-down-v dev-logs \
        migrate-dev migrate-staging migrate-prod \
        ci-local ci-image ci-tf hooks-install

BE := backend
REPO_ROOT := ../../..
DEV_ENV_FILE := infra/envs/dev/.env
# Single source of truth for the image's Python version, same as the Dockerfile/CI use
# (.tool-versions). Read by the two targets that build an image — `dev-up` and `ci-image` — and
# by nothing else: nothing on the staging/prod side needs a Python version at all any more
# (docker-compose.yml has no `build:` section). Not exported: GNU Make exports only variables
# that came from its own environment or the command line, never ones defined here, so a
# `docker compose` child still sees it unset, which is what docker-compose.yml expects.
PYTHON_VERSION := $(shell awk '$$1=="python"{print $$2}' $(REPO_ROOT)/.tool-versions)
# Not derived from a file — this is the dev literal itself (docker-compose.yml's header comment
# explains why `rag-documents:dev` specifically makes the build/pull fallback work). `DEV_` prefix
# because the scope really is dev-only: this is only ever the *default* value handed to
# the `IMAGE` env var dev commands export — migrate-staging/migrate-prod below never reference it
# at all, they rely entirely on a command-line `IMAGE=<digest>` override instead (see their own
# comment) — a generic `IMAGE` name here would suggest it's the one shared source, which it isn't.
DEV_IMAGE := rag-documents:dev
# What `ci-image` builds and measures — the same tag and the same ceiling CI uses, so the number
# a developer sees locally is the number that gates the PR.
CI_IMAGE := rag-documents:ci
MAX_IMAGE_MB := 900
# One prefix instead of repeating four parts on six recipes. `-f docker-compose.dev.yml` is the
# dev-only overlay that publishes the app port to the host (see that file) — it is never synced to
# an instance, which is what keeps 0.0.0.0:8080 off staging/prod. `--env-file` supplies Compose's
# own `${VAR}` interpolation (ENV, EMBEDDING_CACHE_DIR, POSTGRES_SUPERUSER_PASSWORD) from the same
# file the containers read.
#
# IMAGE is the only value passed on the command line, because it is the only one that isn't in
# that file. The superuser password used to be a literal here too, and had to be repeated on every
# recipe — once as this prefix (for Compose's interpolation) and again as `-e` (for the one-off
# `api` containers, which read `env_file:`, not the invoking shell). Moving it into
# infra/envs/dev/.env, where the app role's password already lived, feeds both from one place.
# staging/prod still thread both passwords through by hand: their .env carries neither, on purpose.
DEV_COMPOSE := IMAGE=$(DEV_IMAGE) \
               docker compose -f docker-compose.yml -f docker-compose.dev.yml --env-file $(DEV_ENV_FILE)
# No `-include`/`export` here any more: every `docker compose` recipe below passes `--env-file
# $(DEV_ENV_FILE)` directly (same mechanism `ssm-migrate-deploy` already uses for staging/prod,
# and the one `docker run --env-file` uses for the standalone migration container) plus
# `IMAGE=$(DEV_IMAGE)` inline for the one value that isn't in any `.env` file — explicit
# per-command, not an implicit blanket `export` a reader has to scroll up to find. `--env-file` on
# a missing path fails loud with its own clear error ("couldn't find env file: ...", verified
# live) — no need for `-include`'s softer missing-file tolerance, since nothing here runs at
# Make-parse time any more. `PYTHON_VERSION` feeds only the two `docker build`
# recipes (`dev-up`, `ci-image`) — `docker-compose.yml` has no `build:` section at all (see its own
# header comment), so no compose recipe needs it, and staging/prod don't either any more (the `PYTHON_VERSION=unused`
# placeholder that used to be required on every staging/prod command is gone along with the
# `build:` section that made it necessary).

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-20s\033[0m %s\n",$$1,$$2}'

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

.PHONY: openapi openapi-check
openapi: ## regenerate docs/openapi.json from the code
	cd $(BE) && poetry run python -m scripts.dump_openapi

openapi-check: ## fail if docs/openapi.json is stale (CI parity)
	cd $(BE) && poetry run python -m scripts.dump_openapi --check

# Explicit `docker build`, not `docker compose up --build`: docker-compose.yml has no `build:`
# section (see its own header comment) — this is now the *only* place anything gets built for
# dev, same shape as CI's own `build-push-image` action (`-f`/context/`--build-arg` all mirror
# it). `-f Dockerfile`: relative to this Makefile's own directory (where `make` runs from), same
# file `context: $(REPO_ROOT)` (the true repo root, matching the Dockerfile's own COPY paths) then
# resolves through. `docker compose up -d` afterward finds the freshly-built `$(DEV_IMAGE)` tag
# already in the local image cache — `pull_policy`'s default (`missing`: check local cache, then
# registry) never needs to reach a registry that doesn't have a `rag-documents:dev` tag at all.
#
# `migrate-dev` BEFORE `up -d`, the same order `ssm-migrate-deploy` uses on staging/prod
# (migrations, then role provisioning, then the container swap — frame spec: migrations always
# precede code). It used to be the other way round here, which was a leftover from before the
# provisioning step existed, and it does not merely look inconsistent: on a fresh volume `up -d`
# starts `api` before the app role has been created, so the container fails to authenticate and
# sits in a restart loop until someone runs `migrate-dev` by hand — while `dev-up` itself exits 0,
# reporting success over a stack that cannot serve a request. (Before `scripts/bootstrap.py`
# gained its RLS guard this was merely latent: `get_engine()` builds a pool without connecting,
# so the process started and only failed per-request.)
#
# No `up -d postgres` needed first: `migrate-dev`'s `docker compose run api` creates the network
# and volumes, starts `postgres` and waits for it to become healthy on its own, through the `api`
# service's `depends_on: condition: service_healthy` — verified from a completely clean slate.
dev-up: ## build, migrate, then start the local stack (creates the backbone network if missing)
	docker network create backbone 2>/dev/null || true
	docker build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -f Dockerfile -t $(DEV_IMAGE) $(REPO_ROOT)
	$(MAKE) migrate-dev
	$(DEV_COMPOSE) up -d
dev-down: ## stop the dev stack
	$(DEV_COMPOSE) down
dev-down-v: ## stop + wipe volumes (fresh DB + model cache)
	$(DEV_COMPOSE) down -v
dev-logs: ## follow stack logs
	$(DEV_COMPOSE) logs -f

# python -m, not bare `alembic`: the console script's shebang breaks once relocated into the
# runtime image (see .build-state/R-25-.../clarifications.md) — same fix as the Dockerfile's CMD.
# Both steps override the container's CMD (bypassing scripts.bootstrap), and both are ELEVATED:
# migrations/env.py and scripts/provision_app_role.py each build their DSN from
# POSTGRES_SUPERUSER/POSTGRES_SUPERUSER_PASSWORD, not the app's own credentials (see their
# docstrings — CREATE EXTENSION and CREATE POLICY are superuser/owner-only, and the app role must
# hold neither privilege). In dev that pair comes from infra/envs/dev/.env like everything else,
# via the `api` service's own `env_file:` — no `-e` needed here, unlike migrate-staging/prod below,
# whose .env deliberately carries no password at all. HOST/PORT default to postgres/5432, matching
# docker-compose.yml's `postgres` service.
#
# Two steps, always in this order: `upgrade head` creates the tables as the superuser that owns
# them, then provisioning grants the app role plain DML on whatever now exists — so a migration
# that adds a table is covered by the same run that creates it. Provisioning is also what applies
# a rotated `db-password`: nothing else in the stack ever changes the role's password (the
# postgres image sets it at initdb only, and pgdata outlives restarts), so a rotation takes effect
# on the next deploy, not on a bare `api` restart.
migrate-dev: ## alembic upgrade head + provision the app role, against the compose Postgres
	$(DEV_COMPOSE) run --rm api python -m alembic upgrade head
	$(DEV_COMPOSE) run --rm api python -m scripts.provision_app_role
# The pipelines invoke this exact command inline via SSM Run Command, not this target — it exists
# for an operator to reproduce/troubleshoot the same migration manually on the instance itself
# (where there's a deployed container, not a poetry-managed checkout, and where AWS creds for the
# `aws secretsmanager` call below are already available via the instance's own role). Requires
# IMAGE=<digest>. `docker compose run`, not a bare `docker run`: auto-joins the compose project's
# own network (no manual `--network` needed) and, via `postgres`'s own `depends_on: condition:
# service_healthy`, creates+waits for `postgres` automatically if it isn't already running —
# verified live from a clean slate (no network/containers/volumes at all), see
# .build-state/R-25-.../clarifications.md. `--env-file` supplies POSTGRES_USER/POSTGRES_DB/
# EMBEDDING_CACHE_DIR/ENV straight from the instance's synced .env for Compose's own interpolation
# (`postgres`'s block reads USER/DB via its own `env_file:` key instead, a separate mechanism —
# see docker-compose.yml). Two secrets, not one, and neither is ever in a .env file:
# `db-superuser-password` is the `postgres` container's own bootstrap identity, `db-password` is
# the app role's — see docker-compose.yml for why they must not be the same value.
# POSTGRES_SUPERUSER_PASSWORD needs setting *twice* on each line: once on the host CLI (feeds
# `postgres`'s `environment: {POSTGRES_PASSWORD: ${POSTGRES_SUPERUSER_PASSWORD}}` block, which
# Compose still parses even though only `api` is being run) and once via `docker compose run`'s
# own `-e` flag (`api`'s service definition has no other way to receive it — it only has
# `env_file:`, and both invocations override the container's CMD, bypassing `scripts.bootstrap`'s
# own Secrets Manager fetch entirely) — found for real: without the second one, the container
# fails with `KeyError` inside `migrations/env.py`. POSTGRES_PASSWORD (the app role's) is needed
# only by the second line, which is the one that sets that role's password.
#
# Every value is quoted at its point of use (`-e "VAR=$$PW"`): unquoted, a Secrets-Manager
# password containing a space would split into two `docker compose` arguments ("no such service"),
# and one containing `*` or `?` would glob against the working directory and hand the container a
# different string than the secret holds. The `VAR=$$PW` assignment *prefix* at the start of the
# line is exempt from both by shell rules, which is exactly what made the inconsistency easy to
# miss when only the prefix form was there.
# `\`: a Makefile recipe runs each line in its own shell by default, so the `PGPW` set here
# wouldn't otherwise survive to the next line. No PYTHON_VERSION here (or anywhere below) — docker-
# compose.yml has no `build:` section, so Compose never needs it, on the instance or anywhere else.
# No `IMAGE=$(DEV_IMAGE)` prefix, unlike the dev targets above: GNU Make automatically exports a
# variable set on the command line (`make migrate-staging IMAGE=<digest>`) to every child
# process's environment, whether or not the recipe's own text references it, and whether or not
# any Makefile variable of that name even exists — verified live, including with `IMAGE` entirely
# undeclared anywhere in this file. That makes an explicit prefix redundant when IMAGE *is* passed
# correctly, but its absence also closes a real gap: this file's `DEV_IMAGE`/`rag-documents:dev`
# default is never in play here at all (nothing below references `$(DEV_IMAGE)`) — so if IMAGE is
# ever forgotten on the command line, the child `docker compose` process sees it as genuinely
# unset and hits its own `${IMAGE:?...}` check, rather than any dev value silently substituting
# for it against a real staging/prod database.
migrate-staging: ## run by the deploy-staging pipeline via SSM; manual use: make migrate-staging IMAGE=<repo>@<digest>
	PGPW=$$(aws secretsmanager get-secret-value --secret-id holahost/staging/rag-documents/db-password --query SecretString --output text); \
	SUPERPW=$$(aws secretsmanager get-secret-value --secret-id holahost/staging/rag-documents/db-superuser-password --query SecretString --output text); \
	cd /opt/services/rag-documents && \
	POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW docker compose --env-file infra/envs/staging/.env run --rm -e "POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW" api python -m alembic upgrade head && \
	POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW docker compose --env-file infra/envs/staging/.env run --rm -e "POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW" -e "POSTGRES_PASSWORD=$$PGPW" api python -m scripts.provision_app_role
migrate-prod: ## run by the promote-prod pipeline via SSM; manual use: make migrate-prod IMAGE=<repo>@<digest>
	PGPW=$$(aws secretsmanager get-secret-value --secret-id holahost/prod/rag-documents/db-password --query SecretString --output text); \
	SUPERPW=$$(aws secretsmanager get-secret-value --secret-id holahost/prod/rag-documents/db-superuser-password --query SecretString --output text); \
	cd /opt/services/rag-documents && \
	POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW docker compose --env-file infra/envs/prod/.env run --rm -e "POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW" api python -m alembic upgrade head && \
	POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW docker compose --env-file infra/envs/prod/.env run --rm -e "POSTGRES_SUPERUSER_PASSWORD=$$SUPERPW" -e "POSTGRES_PASSWORD=$$PGPW" api python -m scripts.provision_app_role

# Bare `pre-commit`, NOT `poetry run pre-commit` from inside backend/: the repo-root
# .pre-commit-config.yaml's hooks auto-discover and `cd`+`poetry run` into EVERY package
# (including holahost-auth) — running the outer `pre-commit` itself via this package's own
# activated venv leaks that venv's VIRTUAL_ENV into those subprocess calls, breaking poetry's venv
# resolution for every OTHER package's hook run (found for real: holahost-auth's own `poetry run
# mypy` started failing on missing test-only deps that its own venv actually has, only when
# invoked this way — see .build-state/R-25-.../clarifications.md). Must run from the true repo
# root — the hooks' file paths and discovery are repo-root-relative.
hooks-install: ## install git hooks (repo-root pre-commit config)
	cd $(REPO_ROOT) && pre-commit install
# Three targets, not one, and the split is the honest part. `ci-local` used to promise "local
# parity with the ci pipeline" while running only pre-commit and pytest — so a renamed route or a
# response field that quietly became optional passed locally and failed the PR on `openapi-check`,
# the one check most likely to catch exactly that. What CI runs and these three cover between them:
# pre-commit, unit + integration tests, openapi-check (ci-local); docker build and §12's size
# budget (ci-image); terraform validate on all three roots (ci-tf). What is deliberately NOT
# covered: `terraform plan`, which needs the platform AWS account and a role that does not exist
# yet, and is gated on `vars.AWS_ACCOUNT_ID` in CI for the same reason.
ci-local: ## pre-commit + the full test suite + the OpenAPI contract check (no Docker/Terraform)
	cd $(REPO_ROOT) && pre-commit run --all-files
	cd $(BE) && poetry run pytest
	$(MAKE) openapi-check
ci-image: ## the CI checks that need Docker: build the image, then §12's size budget
	docker build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -f Dockerfile -t $(CI_IMAGE) $(REPO_ROOT)
	@size_mb=$$(( $$(docker image inspect $(CI_IMAGE) --format '{{.Size}}') / 1000000 )); \
	echo "$(CI_IMAGE) is $${size_mb} MB (ceiling $(MAX_IMAGE_MB) MB)"; \
	if [ "$$size_mb" -gt "$(MAX_IMAGE_MB)" ]; then \
		echo "image grew past the §12 budget — check .dockerignore and new dependencies"; \
		exit 1; \
	fi
# `-backend=false`: validate needs no state and no credentials, which is exactly why CI can run it
# on a fork PR. Same three roots, same order.
ci-tf: ## the CI checks that need Terraform: validate common + both env roots
	cd infra/common && terraform init -backend=false && terraform validate
	cd infra/envs/staging && terraform init -backend=false && terraform validate
	cd infra/envs/prod && terraform init -backend=false && terraform validate

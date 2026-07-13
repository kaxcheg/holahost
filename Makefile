# hola.host monorepo orchestrator. Backend cmds run via `poetry run` for CI parity; frontend via npm.
.DEFAULT_GOAL := help
.PHONY: help lint format typecheck test test-int lint-imports check-versions \
        validate-sample-messages \
        export-openapi check-openapi export-frontend-constants check-frontend-constants \
        fe-install fe-lint fe-typecheck fe-test fe-build fe-generate-types \
        dev-up dev-down dev-down-v dev-logs migrate-dev dev-test \
        migrate-staging migrate-prod ci-local hooks-install

DEV_DATABASE_URL ?= postgresql://holahost:holahost@localhost:5432/holahost

# Component locations (monorepo: Holahost app + the lead-capture microservice).
BE := holahost/services/lead-capture/backend
FE := holahost/frontend

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-26s\033[0m %s\n",$$1,$$2}'

## ── Backend quality (CI parity) ──────────────────────────────────────────────
lint: ## ruff lint (backend)
	cd $(BE) && poetry run ruff check app tests
format: ## ruff format (backend)
	cd $(BE) && poetry run ruff format app tests
typecheck: ## mypy strict (backend app)
	cd $(BE) && poetry run mypy app
test: ## unit tests (no Docker)
	cd $(BE) && poetry run pytest -m "not integration"
test-int: ## integration tests (testcontainers; needs Docker)
	cd $(BE) && poetry run pytest -m integration
lint-imports: ## clean-architecture import contract
	$(MAKE) -C $(BE) lint-imports
check-versions: ## verify toolchain versions agree across manifests (.tool-versions is the source)
	cd $(BE) && poetry run python $(CURDIR)/scripts/check_versions.py
validate-sample-messages: ## docs/sample_messages.json is a non-empty JSON array of non-empty strings (C-10b)
	cd $(BE) && poetry run python $(CURDIR)/scripts/validate_sample_messages.py
export-openapi: ; $(MAKE) -C $(BE) export-openapi
check-openapi: ; $(MAKE) -C $(BE) check-openapi
export-frontend-constants: ; $(MAKE) -C $(BE) export-frontend-constants
check-frontend-constants: ; $(MAKE) -C $(BE) check-frontend-constants

## ── Frontend ─────────────────────────────────────────────────────────────────
fe-install: ; npm ci --prefix $(FE)
fe-lint: ; npm run lint --prefix $(FE)
fe-typecheck: ; npm run typecheck --prefix $(FE)
fe-test: ; npm test --prefix $(FE)
fe-build: ; npm run build --prefix $(FE)
fe-generate-types: ; npm run generate-types --prefix $(FE)

## ── Local dev stack (I-02) ───────────────────────────────────────────────────
dev-up: ## build + start the stack; prompts for the Anthropic key (SAMPLE_SERVER_API_KEY) if unset
	@if [ -z "$$SAMPLE_SERVER_API_KEY" ]; then \
		printf "SAMPLE_SERVER_API_KEY (Anthropic key, input hidden): "; \
		stty -echo 2>/dev/null; read -r SAMPLE_SERVER_API_KEY; stty echo 2>/dev/null; echo; \
	fi; \
	export SAMPLE_SERVER_API_KEY; \
	export PYTHON_VERSION="$$(awk '$$1=="python"{print $$2}' .tool-versions)"; \
	docker compose up -d --build
dev-down: ## stop the dev stack
	docker compose down
dev-down-v: ## stop + wipe volumes (fresh DB)
	docker compose down -v
dev-logs: ## follow stack logs
	docker compose logs -f
migrate-dev: ## alembic upgrade head against the compose Postgres
	cd $(BE) && DATABASE_URL=$(DEV_DATABASE_URL) poetry run alembic upgrade head
dev-test: ## integration suite (testcontainers spins its own PG)
	cd $(BE) && poetry run pytest -m integration

## ── Deploy migration wrappers (run by CI; §13.5; gated in settings) ──────────
migrate-staging: ; cd $(BE) && poetry run alembic upgrade head
migrate-prod: ; cd $(BE) && poetry run alembic upgrade head

## ── Aggregate ────────────────────────────────────────────────────────────────
hooks-install: ## install git hooks (pre-commit + commit-msg stages, §13.3)
	cd $(BE) && poetry run pre-commit install
ci-local: ## §13.4 local CI parity
	$(MAKE) check-versions
	cd $(BE) && poetry run pre-commit run --all-files
	cd $(BE) && poetry run pytest
	npm test --prefix $(FE)
	npm run build --prefix $(FE)

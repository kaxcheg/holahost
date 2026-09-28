# The dev minter: its package's gates, and its container on `backbone`.
#
#   make dev-up                               build the image and start the minter
#   export HOLAHOST_TOKEN=$(make -s token)    a token for guest-reply-cli
#
# From the repository root: `make -s -C holahost/tools/dev-minter token`.

REPO_ROOT ?= ../../..
# The image's Python version, from the one source the services' images and CI read too.
PYTHON_VERSION := $(shell awk '$$1=="python"{print $$2}' $(REPO_ROOT)/.tool-versions)
IMAGE ?= dev-minter:dev
COMPOSE ?= docker compose -f docker-compose.yml

.DEFAULT_GOAL := help
.PHONY: help lint format typecheck lint-imports test dev-up dev-down dev-down-v dev-logs token

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

lint: ## ruff check
	poetry run ruff check .
format: ## ruff format
	poetry run ruff format .
typecheck: ## mypy strict, whole package
	poetry run mypy .
lint-imports: ## import contract
	poetry run lint-imports
test: ## unit tests (no Docker)
	poetry run pytest

dev-up: ## build the image and start the minter on backbone (creates the network if missing)
	docker network create backbone 2>/dev/null || true
	docker build --build-arg PYTHON_VERSION=$(PYTHON_VERSION) -t $(IMAGE) .
	$(COMPOSE) up -d
dev-down: ## stop the minter; the key survives
	$(COMPOSE) down
dev-down-v: ## stop the minter and delete its key — every token minted so far stops validating
	$(COMPOSE) down -v
dev-logs: ## follow the minter's log
	$(COMPOSE) logs -f
token: ## print a guest-reply-cli token, and nothing else, on stdout
	@$(COMPOSE) exec -T dev-minter python -m dev_minter mint

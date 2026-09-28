# guest-reply's gates. A console tool: no image and no stack of its own — the tests fake HTTP.

.DEFAULT_GOAL := help
.PHONY: help lint format typecheck lint-imports test ci-local

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-12s\033[0m %s\n",$$1,$$2}'

lint: ## ruff check
	poetry run ruff check .
format: ## ruff format
	poetry run ruff format .
typecheck: ## mypy strict, whole package
	poetry run mypy .
lint-imports: ## the dependency rule: clients know nothing about commands
	poetry run lint-imports
test: ## unit tests (HTTP faked; no stack needed)
	poetry run pytest
ci-local: ## what tools-ci runs for this package
	poetry run ruff check . && poetry run ruff format --check . && poetry run mypy . \
		&& poetry run lint-imports && poetry run pytest -q

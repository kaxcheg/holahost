# Repo-level entry points. Per-service targets (build, test, migrate, deploy parity) live in the
# service's own Makefile, which includes holahost/make/common.mk.

.DEFAULT_GOAL := help
.PHONY: help hooks-install check

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*## "}{printf "  \033[36m%-16s\033[0m %s\n",$$1,$$2}'

hooks-install: ## install the pre-commit and commit-msg git hooks
	pre-commit install

# Bare `pre-commit`, not `poetry run pre-commit`: the hooks below cd and `poetry run` into every
# package in the repo, and running the outer tool through one package's venv leaks its VIRTUAL_ENV
# into those subprocesses.
check: ## run every hook over the whole repo
	pre-commit run --all-files

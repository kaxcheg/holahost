.PHONY: lint-imports export-openapi check-openapi

# Enforce the Clean Architecture boundary: application/domain must not import the RAG stack
# (langchain / fastembed). Run from app/ so import-linter resolves the top-level packages.
lint-imports:
	cd app && PYTHONPATH=. poetry run lint-imports --config ../pyproject.toml

# Regenerate the OpenAPI contract consumed by the frontend type codegen (spec §11.3, F-06).
# Writes <repo>/docs/openapi.yaml from the live backend symbols (router / DTOs / error map).
export-openapi:
	cd app && PYTHONPATH=. poetry run python scripts/export_openapi.py

# CI drift guard: regenerate and fail if docs/openapi.yaml is stale vs the backend contract.
# Wire this into the future ci.yml frontend job (spec §13.4) alongside the generated.ts check.
check-openapi: export-openapi
	git diff --exit-code -- ../docs/openapi.yaml

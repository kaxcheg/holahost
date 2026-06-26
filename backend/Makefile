.PHONY: lint-imports

# Enforce the Clean Architecture boundary: application/domain must not import the RAG stack
# (langchain / fastembed). Run from app/ so import-linter resolves the top-level packages.
lint-imports:
	cd app && PYTHONPATH=. poetry run lint-imports --config ../pyproject.toml

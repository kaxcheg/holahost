"""Check `registry.yaml` the way startup does, with no environment and no keys.

A registry error stops the process at startup; this runs the same two steps — reading the file
(`config.registry`) and building its domain objects against the adapters the service has
(`infrastructure.registry`) — so CI refuses the change instead of the rollout. Neither step reads a
setting or a secret: which provider is enabled and what its key is called are the file's own, and
whether the key exists in Secrets Manager is the environment root's check (`terraform validate`).

One rule is the pipelines' rather than the startup's: the alias the rollout's paid smoke calls must
resolve to a candidate, or every rollout fails after the container swap.

`make validate-registry`; an optional argument names another file, for trying out a change.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from config.registry import REGISTRY_PATH, read_registry
from infrastructure.providers.dialects import DIALECTS
from infrastructure.registry.config_providers_repo import (
    InvalidRegistryError,
    load_providers_repo,
)

# The alias the rollout's paid smoke generates on — `.github/workflows/llm-client-*.yml`.
SMOKE_ALIAS = "fast"


def main(argv: list[str]) -> int:
    path = Path(argv[0]) if argv else REGISTRY_PATH
    try:
        registry = read_registry(path)
        repo = load_providers_repo(registry, supported=DIALECTS)
    except (OSError, yaml.YAMLError, ValidationError, InvalidRegistryError) as error:
        print(f"{path}: {error}", file=sys.stderr)
        return 1
    if not repo.resolve(SMOKE_ALIAS):
        print(
            f"{path}: alias {SMOKE_ALIAS!r} has no enabled candidate, and the rollout's smoke "
            "calls it",
            file=sys.stderr,
        )
        return 1
    print(f"registry is valid: {len(registry.providers)} providers, {len(repo.aliases())} aliases")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

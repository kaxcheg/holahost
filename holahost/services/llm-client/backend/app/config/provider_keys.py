"""Where a provider's API key is read from: the environment variable named after its reference.

Read once, at startup, and never through `Settings`: a key is a credential only the generation
adapter needs, and every other holder of `Settings` would see it too. On staging and prod the
variables are filled from Secrets Manager by `scripts/bootstrap.py` before anything reads them; on
dev `infra/envs/dev/.env` sets them.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import SecretStr

from config.registry import RegistryFile


class MissingProviderKeyError(RuntimeError):
    """An enabled provider has no key in the environment: the service must not start."""


def key_variable(ref: str) -> str:
    """The variable a secret reference is read from: `anthropic-api-key` → `ANTHROPIC_API_KEY`."""
    return ref.upper().replace("-", "_")


def read_provider_keys(registry: RegistryFile, environ: Mapping[str, str]) -> dict[str, SecretStr]:
    """Every enabled provider's key, by provider name.

    :raises MissingProviderKeyError: a variable is unset or blank — naming every one missing.
    """
    keys: dict[str, SecretStr] = {}
    missing: list[str] = []
    for provider, ref in registry.enabled_key_refs().items():
        value = environ.get(key_variable(ref), "")
        if value.strip():
            keys[provider] = SecretStr(value)
        else:
            missing.append(key_variable(ref))
    if missing:
        raise MissingProviderKeyError(f"no provider key in the environment: {', '.join(missing)}")
    return keys

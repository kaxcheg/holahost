"""Cold-start secret loading from AWS Secrets Manager into `os.environ` (§3.8).

Staging/prod: the composition root (R-24) calls `load_secret_into_env` for each
server-side secret BEFORE `Settings` is constructed; `pydantic-settings` then reads
them as ordinary env vars. Dev never calls this — secrets come from `.env.dev`.
`boto3` is imported lazily so a dev process that never reaches Secrets Manager doesn't
pay for the import.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mypy_boto3_secretsmanager import SecretsManagerClient


class _SecretsClient(Protocol):
    def get_secret_value(self, SecretId: str) -> dict[str, str]: ...


def make_secrets_client(region: str) -> SecretsManagerClient:
    """Build a Secrets Manager client bound to an explicit region (no ambient discovery)."""
    import boto3

    return boto3.session.Session().client("secretsmanager", region_name=region)


def load_secret_into_env(env: str, name: str, env_var: str, client: _SecretsClient) -> None:
    """Fetch one service-scoped secret and set `os.environ[env_var]` (§3.8).

    Secret id: `holahost/{env}/rag-documents/{name}` — service-scoped (unlike
    `~/repos/lead-capture`'s flat `holahost/{env}/{name}`, which predates a second
    service existing; scoping avoids collisions now that it isn't the only one).
    """
    secret_id = f"holahost/{env}/rag-documents/{name}"
    secret = client.get_secret_value(SecretId=secret_id)
    os.environ[env_var] = secret["SecretString"]

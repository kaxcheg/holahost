"""Cold-start secret loading from AWS Secrets Manager into `os.environ` (§3.8).

Staging/prod: the composition root (R-24) calls `load_secret_into_env` for each
server-side secret BEFORE `Settings` is constructed; `pydantic-settings` then reads
them as ordinary env vars. Dev never calls this — secrets come from `.env.dev`.
`boto3` is imported lazily so a dev process that never reaches Secrets Manager doesn't
pay for the import.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from mypy_boto3_secretsmanager import SecretsManagerClient


class SecretsClient(Protocol):
    """What `load_secret_into_env` needs from a Secrets Manager client.

    Public (not `_SecretsClient`): the composition root (R-24, `scripts/bootstrap.py`)
    is a real external consumer, not just this module's own tests.

    Return type is `Mapping[str, Any]`, not `dict[str, str]`: boto3's real
    `GetSecretValueResponseTypeDef` (what `make_secrets_client`'s `SecretsManagerClient`
    actually returns) is a TypedDict with non-str fields (`SecretBinary: bytes`,
    `CreatedDate: datetime`, ...) — this Protocol only ever reads the `"SecretString"`
    key, so it doesn't need every value typed as `str`, just read access.

    The real `SecretsManagerClient.get_secret_value` is typed as
    `(self, **kwargs: Unpack[GetSecretValueRequestTypeDef]) -> ...` in boto3-stubs —
    functionally identical to `(self, SecretId: str) -> ...` at the one call site here
    (`client.get_secret_value(SecretId=...)` works against both), but mypy doesn't
    recognize `Unpack[TypedDict]` kwargs as structurally satisfying an explicit-param
    Protocol, hence the `cast` at `make_secrets_client`'s one call site
    (`scripts/bootstrap.py`) rather than a signature this Protocol can't actually use.
    """

    def get_secret_value(self, SecretId: str) -> Mapping[str, Any]: ...


def make_secrets_client(region: str) -> SecretsManagerClient:
    """Build a Secrets Manager client bound to an explicit region (no ambient discovery)."""
    import boto3

    return boto3.session.Session().client("secretsmanager", region_name=region)


def load_secret_into_env(env: str, name: str, env_var: str, client: SecretsClient) -> None:
    """Fetch one service-scoped secret and set `os.environ[env_var]` (§3.8).

    Secret id: `holahost/{env}/rag-documents/{name}` — service-scoped (unlike
    `~/repos/lead-capture`'s flat `holahost/{env}/{name}`, which predates a second
    service existing; scoping avoids collisions now that it isn't the only one).
    """
    secret_id = f"holahost/{env}/rag-documents/{name}"
    secret = client.get_secret_value(SecretId=secret_id)
    os.environ[env_var] = secret["SecretString"]

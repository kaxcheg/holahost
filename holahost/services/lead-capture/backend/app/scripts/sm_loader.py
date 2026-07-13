"""Cold-start secret loading from AWS Secrets Manager into os.environ (spec §10.3, C-6).

In staging/prod the bootstrap loads exactly the four server-side secrets BEFORE ``Settings`` is
built; pydantic-settings then reads them as ordinary env vars. The store id is
``holahost/{env}/<name>`` and the env-var name is the upper-cased key (identity map — no rename).
Dev does not call this (secrets come from ``.env``).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_secretsmanager import SecretsManagerClient

SERVER_SIDE_SECRET_KEYS = (
    "database_url",
    "resend_api_key",
    "ip_hash_salt",
    "sample_server_api_key",
)


def load_secrets_into_env(env: str, client: SecretsManagerClient) -> None:
    """Fetch each server-side secret and set ``os.environ[KEY.upper()]`` (cold start, §10.3)."""
    for key in SERVER_SIDE_SECRET_KEYS:
        secret = client.get_secret_value(SecretId=f"holahost/{env}/{key}")
        os.environ[key.upper()] = secret["SecretString"]

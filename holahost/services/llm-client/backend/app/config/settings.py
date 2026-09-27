"""Typed runtime configuration, loaded from environment variables.

One class with an `env` discriminator rather than per-env subclasses: there is a single
config source (`os.environ`), and staging/prod populate the secret-backed variables before
this class is constructed (see `scripts/bootstrap.py`).

Inherits the application's Postgres identity from `holahost_db.AppRoleSettings`, so those
credentials have one declaration shared with `scripts/provision_app_role.py`. The superuser
pair lives in `SuperuserSettings`, a separate model, and never reaches this class — which
is what keeps a serving process from holding the credential that runs the DDL. A service
that stores nothing drops `AppRoleSettings` and inherits nothing.

The five token-validation variables are not here at all: `holahost_auth.AuthConfig` reads
those itself, because their names are a platform contract and only `expected_audience`
differs per service.

Domain limits do NOT belong here. A maximum size, an allowed format, a threshold — those
are application constants, co-located with the code that enforces them, and making them
per-environment settings means staging and prod can disagree about what the service
accepts.
"""

from __future__ import annotations

from typing import Literal

from holahost_db import AppRoleSettings
from pydantic import Field


class Settings(AppRoleSettings):
    env: Literal["dev", "staging", "prod"]

    # The budget's ceilings per window, input and output apart: the prices differ by a multiple,
    # and one counter would lie. Settings rather than constants: they say how much this deployment
    # may spend, and staging rightly spends less than prod.
    budget_cap_client_input_tokens: int = Field(gt=0)
    budget_cap_client_output_tokens: int = Field(gt=0)
    budget_cap_client_downgrade_input_tokens: int = Field(gt=0)
    budget_cap_client_downgrade_output_tokens: int = Field(gt=0)
    budget_cap_provider_input_tokens: int = Field(gt=0)
    budget_cap_provider_output_tokens: int = Field(gt=0)

    idempotency_key_ttl_seconds: int = Field(gt=0)

    # Two dimensions, N ceilings: the bucket says how expensive the operation is, the
    # identity kind says what the ceiling counts. A service token's counter is one
    # aggregate for the calling service; an exchanged token's is per user of that client.
    # One number for both would starve a busy integration or hand each of its users the
    # whole integration's allowance.
    rate_limit_user_generate: int = Field(gt=0)
    rate_limit_service_generate: int = Field(gt=0)

    @classmethod
    def from_env(cls) -> Settings:
        """Build `Settings` from environment variables (composition root)."""
        return cls()

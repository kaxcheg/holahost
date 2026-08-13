from __future__ import annotations

import os
from typing import Any

import pytest

from config.sm_loader import load_secret_into_env


class _FakeSecretsClient:
    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets
        self.requested_ids: list[str] = []

    def get_secret_value(self, SecretId: str) -> dict[str, Any]:
        self.requested_ids.append(SecretId)
        return {"SecretString": self._secrets[SecretId]}


class TestLoadSecretIntoEnv:
    def test_sets_the_env_var_from_the_secret_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _FakeSecretsClient({"holahost/staging/rag-documents/db-password": "s3cr3t"})

        load_secret_into_env(
            env="staging",
            name="db-password",
            env_var="DB_PASSWORD",
            client=client,
        )

        assert os.environ["DB_PASSWORD"] == "s3cr3t"
        monkeypatch.delenv("DB_PASSWORD", raising=False)

    def test_uses_the_service_scoped_secret_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _FakeSecretsClient({"holahost/prod/rag-documents/db-password": "x"})

        load_secret_into_env(
            env="prod",
            name="db-password",
            env_var="DB_PASSWORD",
            client=client,
        )

        assert client.requested_ids == ["holahost/prod/rag-documents/db-password"]
        monkeypatch.delenv("DB_PASSWORD", raising=False)

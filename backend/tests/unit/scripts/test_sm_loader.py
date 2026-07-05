import os

import pytest

from scripts.sm_loader import SERVER_SIDE_SECRET_KEYS, load_secrets_into_env


class _FakeSM:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_secret_value(self, SecretId: str) -> dict[str, str]:
        self.requested.append(SecretId)
        return {"SecretString": f"val::{SecretId}"}


def test_keys_are_the_four_required() -> None:
    assert set(SERVER_SIDE_SECRET_KEYS) == {
        "database_url",
        "resend_api_key",
        "ip_hash_salt",
        "sample_server_api_key",
    }


def test_load_secrets_populates_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in SERVER_SIDE_SECRET_KEYS:
        monkeypatch.delenv(key.upper(), raising=False)  # tracked → restored on teardown
    sm = _FakeSM()
    load_secrets_into_env("staging", sm)
    assert os.environ["DATABASE_URL"] == "val::holahost/staging/database_url"
    assert os.environ["SAMPLE_SERVER_API_KEY"] == "val::holahost/staging/sample_server_api_key"
    assert sm.requested == [f"holahost/staging/{k}" for k in SERVER_SIDE_SECRET_KEYS]

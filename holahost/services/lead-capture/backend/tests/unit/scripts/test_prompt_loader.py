import os

import pytest

from scripts.prompt_loader import load_system_prompt_into_env


class _FakeBody:
    def read(self) -> bytes:
        return b"You are a helpful STR host assistant."


class _FakeS3:
    def __init__(self) -> None:
        self.requested: list[tuple[str, str]] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, _FakeBody]:
        self.requested.append((Bucket, Key))
        return {"Body": _FakeBody()}


def test_load_system_prompt_populates_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYSTEM_PROMPT", raising=False)
    s3 = _FakeS3()
    load_system_prompt_into_env(s3, bucket="holahost-frontend", key="system-prompt/staging.md")
    assert os.environ["SYSTEM_PROMPT"] == "You are a helpful STR host assistant."
    assert s3.requested == [("holahost-frontend", "system-prompt/staging.md")]

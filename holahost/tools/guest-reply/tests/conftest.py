"""Every test starts from an environment without the tool's variables, whatever the shell has."""

from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import pytest


@pytest.fixture(autouse=True)
def _no_holahost_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith("HOLAHOST_"):
            monkeypatch.delenv(name)


@pytest.fixture
def http() -> Iterator[httpx.Client]:
    with httpx.Client() as client:
        yield client

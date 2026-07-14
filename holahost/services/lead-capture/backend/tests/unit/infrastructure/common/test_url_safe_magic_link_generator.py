from __future__ import annotations

import re

import pytest

from domain.value_objects.magic_link import MagicLink
from infrastructure.common.url_safe_magic_link_generator import UrlSafeMagicLinkGenerator

_URL_SAFE = re.compile(r"^[A-Za-z0-9_-]+\Z")


def test_generate_returns_url_safe_magic_link() -> None:
    gen = UrlSafeMagicLinkGenerator(32)
    ml = gen.generate()
    assert isinstance(ml, MagicLink)
    token = ml.value.get_secret_value()
    assert _URL_SAFE.match(token)
    assert len(token) == 43  # secrets.token_urlsafe(32) is deterministically 43 chars


def test_generate_is_unique_across_samples() -> None:
    gen = UrlSafeMagicLinkGenerator(32)
    tokens = {gen.generate().value.get_secret_value() for _ in range(1000)}
    assert len(tokens) == 1000


def test_rejects_non_positive_token_bytes() -> None:
    with pytest.raises(ValueError):
        UrlSafeMagicLinkGenerator(0)

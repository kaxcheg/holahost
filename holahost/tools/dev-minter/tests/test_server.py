"""The JWKS endpoint: the public key, and nothing else."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from dev_minter.keys import SigningKey, load_or_create
from dev_minter.server import JWKS_PATH, jwks_document, make_server


@pytest.fixture
def key(tmp_path: Path) -> SigningKey:
    return load_or_create(tmp_path)


@pytest.fixture
def base_url(key: SigningKey) -> Iterator[str]:
    server = make_server(jwks_document(key), host="127.0.0.1", port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_the_jwks_carries_the_public_key(key: SigningKey, base_url: str) -> None:
    with urllib.request.urlopen(base_url + JWKS_PATH) as response:
        assert response.headers["Content-Type"] == "application/json"
        assert response.headers["Cache-Control"] == "max-age=300"
        assert json.load(response) == {"keys": [key.public_jwk()]}


def test_a_query_string_is_ignored(key: SigningKey, base_url: str) -> None:
    with urllib.request.urlopen(f"{base_url}{JWKS_PATH}?x=1") as response:
        assert json.load(response) == {"keys": [key.public_jwk()]}


def test_any_other_path_is_not_found(base_url: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(base_url + "/signing-key.pem")
    assert error.value.code == 404

"""The signing key: created once, reused, and named after itself."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from dev_minter.keys import KEY_FILE, load, load_or_create, thumbprint


def test_load_reads_the_created_key(tmp_path: Path) -> None:
    created = load_or_create(tmp_path)
    assert load(tmp_path).kid == created.kid


def test_load_never_creates(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load(tmp_path)
    assert not (tmp_path / KEY_FILE).exists()


def test_the_first_use_creates_the_key(tmp_path: Path) -> None:
    load_or_create(tmp_path)
    assert (tmp_path / KEY_FILE).exists()


def test_the_key_file_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    load_or_create(tmp_path)
    assert stat.S_IMODE((tmp_path / KEY_FILE).stat().st_mode) == 0o600


def test_a_missing_directory_is_created(tmp_path: Path) -> None:
    load_or_create(tmp_path / "keys")
    assert (tmp_path / "keys" / KEY_FILE).exists()


def test_a_later_use_reuses_the_key(tmp_path: Path) -> None:
    first = load_or_create(tmp_path)
    second = load_or_create(tmp_path)
    assert (first.kid, first.public_jwk()) == (second.kid, second.public_jwk())


def test_a_recreated_key_gets_a_new_kid(tmp_path: Path) -> None:
    first = load_or_create(tmp_path)
    (tmp_path / KEY_FILE).unlink()
    assert load_or_create(tmp_path).kid != first.kid


def test_the_public_jwk_is_one_jwks_entry(tmp_path: Path) -> None:
    key = load_or_create(tmp_path)
    jwk = key.public_jwk()
    assert set(jwk) == {"kty", "n", "e", "kid", "use", "alg"}
    assert (jwk["kty"], jwk["kid"], jwk["use"], jwk["alg"]) == ("RSA", key.kid, "sig", "RS256")


def test_the_kid_is_the_rfc_7638_thumbprint() -> None:
    # RFC 7638 §3.1: the example key and its published thumbprint.
    key = RSAAlgorithm.from_jwk(
        {
            "kty": "RSA",
            "e": "AQAB",
            "n": (
                "0vx7agoebGcQSuuPiLJXZptN9nndrQmbXEps2aiAFbWhM78LhWx4cbbfAAtVT86zwu1RK7aPFFxuhDR1L6tSoc_B"
                "JECPebWKRXjBZCiFV4n3oknjhMstn64tZ_2W-5JsGY4Hc5n9yBXArwl93lqt7_RN5w6Cf0h4QyQ5v-65YGjQR0_F"
                "DW2QvzqY368QQMicAtaSqzs8KJZgnYb9c7d0zgdAZHzu6qMQvRL5hajrn1n91CbOpbISD08qNLyrdkt-bFTWhAI4"
                "vMQFh6WeZu0fM4lFd2NcRwr3XPksINHaQ-G_xBniIqbw0Ls1jF44-csFCur-kEgU8awapJzKnqDKgw"
            ),
        }
    )
    assert isinstance(key, rsa.RSAPublicKey)
    assert thumbprint(key) == "NzbLsXh8uDCcd-6MNwXF4W_7noWXFZAfHkxZsRGC9Xs"

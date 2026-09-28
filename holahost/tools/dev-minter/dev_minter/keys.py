"""The minter's one signing key: created on first use, reused after, never leaves its directory.

In the dev stack the directory is a Docker volume, so `serve` (the long-running container) and
`mint` (`docker compose exec` into it) sign with the same key, and it survives a restart. Deleting
the volume retires every token minted so far.

`kid` is the key's RFC 7638 thumbprint rather than a fixed name: the services' JWKS client refetches
only on an unknown `kid`, so a recreated key has to arrive under a new one — under the old name they
would keep verifying against the key they cached and refuse every new token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ALGORITHM = "RS256"
"""What the services' `EXPECTED_ALGORITHM` pins on dev."""

KEY_FILE = "signing-key.pem"


@dataclass(frozen=True)
class SigningKey:
    private_key: rsa.RSAPrivateKey
    kid: str

    def public_jwk(self) -> dict[str, str]:
        """The public half, as one entry of a JWKS."""
        numbers = _public_numbers(self.private_key.public_key())
        return {**numbers, "kty": "RSA", "kid": self.kid, "use": "sig", "alg": ALGORITHM}


def load_or_create(key_dir: Path) -> SigningKey:
    """The key kept in `key_dir`, created there first if there is none yet — `serve`'s way in.

    Only the server creates: it publishes the JWKS it read at start, so a key created by anything
    else would sign tokens no service can verify.

    :raises OSError: the directory cannot be created, written or read.
    :raises ValueError: the file there is not an unencrypted RSA private key.
    """
    path = key_dir / KEY_FILE
    if not path.exists():
        _create(path)
    return load(key_dir)


def load(key_dir: Path) -> SigningKey:
    """The key kept in `key_dir` — `mint`'s way in.

    :raises FileNotFoundError: there is no key yet; the server creates it when it starts.
    :raises ValueError: the file there is not an unencrypted RSA private key.
    """
    path = key_dir / KEY_FILE
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError(f"{path} does not hold an RSA private key")
    return SigningKey(private_key=key, kid=thumbprint(key.public_key()))


def thumbprint(public_key: rsa.RSAPublicKey) -> str:
    """RFC 7638: SHA-256 over the required members, in lexicographic order, without whitespace."""
    members = {**_public_numbers(public_key), "kty": "RSA"}
    canonical = json.dumps(members, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(canonical).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _create(path: Path) -> None:
    """Write a new key to `path`, whole or not at all: to a temporary file first, then renamed, so
    a `mint` running meanwhile never reads half a key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    # `mkstemp` creates the file readable and writable by its owner only.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(pem)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _public_numbers(public_key: rsa.RSAPublicKey) -> dict[str, str]:
    jwk: dict[str, Any] = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    return {"n": jwk["n"], "e": jwk["e"]}

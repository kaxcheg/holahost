from __future__ import annotations

import hashlib

from pydantic import SecretStr

from domain.value_objects.ip_hash import IpHash


class Sha256IpHasher:
    """Salted SHA-256 hasher mapping a raw client IP to an :class:`IpHash` (spec §8.0, §10.3).

    Digest = ``sha256((salt + ip).encode("utf-8")).hexdigest()`` → 64 lowercase hex chars, which
    satisfies the :class:`IpHash` invariant by construction. Interface-layer utility (no port, C-10).
    """

    def __init__(self, salt: SecretStr) -> None:
        self._salt = salt.get_secret_value()

    def hash(self, ip: str) -> IpHash:
        """Return the salted SHA-256 hash of ``ip`` as an :class:`IpHash`."""
        digest = hashlib.sha256((self._salt + ip).encode("utf-8")).hexdigest()
        return IpHash(digest)

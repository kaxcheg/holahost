from __future__ import annotations

import re
from dataclasses import dataclass

_IP_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class IpHash:
    """SHA-256 IP hash — 64 lowercase hex chars (spec §7.2.3 / §10.5).

    Args:
        value: ``sha256(ip || salt)`` as 64 lowercase hex characters.

    :raises ValueError: If not exactly 64 lowercase hex characters.
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the hex pattern.

        :raises ValueError: If not 64 lowercase hex characters.
        """
        if not _IP_HASH_PATTERN.match(self.value):
            raise ValueError("IpHash: expected 64 lowercase hex chars (SHA-256)")

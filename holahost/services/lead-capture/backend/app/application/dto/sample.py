from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SampleGenerateCmd:
    """Command for POST /api/lead-capture/sample/generate (spec §8.1).

    Args:
        message: Guest message (validated by the use case via GuestMessage.create).
        ip_hash: SHA-256 ip hash computed in the interface layer (primitive).
    """

    message: str
    ip_hash: str


@dataclass(frozen=True)
class SampleGenerateResult:
    """Result of the sample-flow generation (spec §8.1).

    Args:
        response_text: Generated reply text.
    """

    response_text: str

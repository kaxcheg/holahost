from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr


@dataclass(frozen=True)
class GenerateResponseCmd:
    """Command for POST /api/capture-lead/generate (spec §8.1).

    ``guidebook_id`` is intentionally absent: the backend reads ``lead.guidebook_id`` after
    resolving the magic link.

    Args:
        magic_link: Magic-link token (SecretStr).
        byok: Bring-your-own-key Claude API key (SecretStr; never persisted/logged, US-06).
        message: Guest message (validated by the use case).
        ip_hash: SHA-256 ip hash (primitive).
    """

    magic_link: SecretStr
    byok: SecretStr
    message: str
    ip_hash: str


@dataclass(frozen=True)
class GenerateResponseResult:
    """Result of the real-flow generation (spec §8.1).

    Args:
        response_text: Generated reply text.
    """

    response_text: str

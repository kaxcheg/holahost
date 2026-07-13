from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr


@dataclass(frozen=True)
class CaptureLeadCmd:
    """Command for POST /api/capture-lead/leads/capture (spec §8.1).

    Args:
        email: Raw email (validated by the use case via Email VO).
        flow: "guidebook" | "sample"; validated by the use case via LeadFlow.
        ip_hash: SHA-256 ip hash (primitive).
        ua_short: Truncated user-agent, or None.
        honeypot: Hidden anti-bot field (§10.7); a non-empty value triggers a silent reject.
    """

    email: str
    flow: str
    ip_hash: str
    ua_short: str | None
    honeypot: str = ""


@dataclass(frozen=True)
class ResolveMagicLinkCmd:
    """Command for GET /api/capture-lead/magic-link/resolve (spec §8.1).

    Args:
        magic_link: The magic-link token, wrapped in SecretStr to avoid leaking in
            repr/logs (§8.1); validated inside the use case.
        ip_hash: SHA-256 ip hash (primitive).
    """

    magic_link: SecretStr
    ip_hash: str


@dataclass(frozen=True)
class ResolveMagicLinkResult:
    """Result of magic-link resolution (spec §8.1).

    Args:
        email: Lead email.
        flow: Lead flow value ("guidebook" | "sample").
        guidebook_id: UUID string of the attached guidebook, or None.
        guidebook_name: Display name of the attached guidebook, or None.
        guidebook_created_at: ISO-8601 creation timestamp, or None.
    """

    email: str
    flow: str
    guidebook_id: str | None
    guidebook_name: str | None
    guidebook_created_at: str | None

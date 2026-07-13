from __future__ import annotations

from enum import StrEnum, auto

from domain.exceptions import DomainValidationError


class LeadFlow(StrEnum):
    """Lead capture entry point (spec §7.2.5).

    ``StrEnum`` + ``auto()`` yields the lowercase member name as the value, matching the DB
    ``leads.flow`` text values and ``LEAD_FLOW_VALUES`` (§3.0): ``"guidebook"`` / ``"sample"``.
    """

    GUIDEBOOK = auto()
    SAMPLE = auto()

    @classmethod
    def _missing_(cls, value: object) -> LeadFlow:
        """Reject unknown values with a structured domain error (spec §9.0).

        Enum's lookup calls this when ``value`` matches no member; raising here makes
        ``LeadFlow(bad)`` surface as a ``DomainValidationError`` (caught by
        ``payload_validation()`` → 422 ``ERR_INVALID_PAYLOAD``) instead of a bare ``ValueError``.

        :raises DomainValidationError: Always — the value is unknown by construction.
        """
        raise DomainValidationError(
            f"LeadFlow: unknown value {value!r}", field="flow", reason="invalid_format"
        )

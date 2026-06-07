from __future__ import annotations

from enum import StrEnum, auto


class LeadFlow(StrEnum):
    """Lead capture entry point (spec §7.2.5).

    ``StrEnum`` + ``auto()`` yields the lowercase member name as the value, matching the DB
    ``leads.flow`` text values and ``LEAD_FLOW_VALUES`` (§3.0): ``"guidebook"`` / ``"sample"``.
    """

    GUIDEBOOK = auto()
    SAMPLE = auto()

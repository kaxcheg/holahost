from __future__ import annotations

from dataclasses import dataclass

GUIDEBOOK_NAME_MAX_LENGTH = 100  # mirrors prod_hints.json property_name.max_length (§10.6); D6


@dataclass(frozen=True)
class GuidebookName:
    """Display name of a guidebook (spec §7.3; minimal domain invariants — D5/D6).

    Invariants: non-empty (rejects empty / whitespace-only) and
    ``len(value) <= GUIDEBOOK_NAME_MAX_LENGTH`` (100). The 100 cap mirrors ``prod_hints.json``
    ``property_name.max_length`` (§10.6) into the backend as a defense-in-depth safety net (the
    frontend cap can be bypassed); ``prod_hints.json`` remains the product source of truth. The
    value is stored as given (no trimming).

    Args:
        value: The display name.

    :raises ValueError: If empty/whitespace-only, or longer than ``GUIDEBOOK_NAME_MAX_LENGTH``.
    """

    value: str

    def __post_init__(self) -> None:
        """Validate the name is non-empty and within the length cap.

        :raises ValueError: If empty/whitespace-only or too long.
        """
        if not self.value.strip():
            raise ValueError("GuidebookName: empty value")
        if len(self.value) > GUIDEBOOK_NAME_MAX_LENGTH:
            raise ValueError(f"GuidebookName: length > {GUIDEBOOK_NAME_MAX_LENGTH}")

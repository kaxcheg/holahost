from __future__ import annotations

from dataclasses import dataclass

MAX_GUEST_MESSAGE_LENGTH = 4000


@dataclass
class GuestMessage:
    """Transient entity representing a guest's incoming message (spec §7.6).

    Transient: not persisted; lives within a single request. Equality by value (no id field).

    Args:
        text: The stripped message text.
    """

    text: str

    @classmethod
    def create(cls, text: str) -> GuestMessage:
        """Validate and construct a GuestMessage.

        Strips leading/trailing whitespace before validation.

        Args:
            text: Raw message text from the guest.

        Returns:
            A new GuestMessage with stripped text.

        Raises:
            ValueError: If text is empty after stripping or exceeds MAX_GUEST_MESSAGE_LENGTH.
        """
        stripped = text.strip()
        if not stripped:
            raise ValueError("GuestMessage: empty text")
        if len(stripped) > MAX_GUEST_MESSAGE_LENGTH:
            raise ValueError(f"GuestMessage: text > {MAX_GUEST_MESSAGE_LENGTH} chars")
        return cls(text=stripped)

from __future__ import annotations

import re
from dataclasses import dataclass

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\Z")
EMAIL_MAX_LENGTH = 254


@dataclass(frozen=True)
class Email:
    """Email address value object (spec §7.2.2 / §10.7).

    Args:
        value: The raw email address.

    :raises ValueError: If longer than ``EMAIL_MAX_LENGTH`` or it fails ``EMAIL_REGEX``.
    """

    value: str

    def __post_init__(self) -> None:
        """Validate length and format.

        :raises ValueError: If too long or malformed.
        """
        if len(self.value) > EMAIL_MAX_LENGTH:
            raise ValueError(f"Email: length > {EMAIL_MAX_LENGTH}")
        if not EMAIL_REGEX.match(self.value):
            raise ValueError("Email: invalid format")

from __future__ import annotations

import re
from dataclasses import dataclass

from domain.exceptions import DomainValidationError

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\Z")
EMAIL_MAX_LENGTH = 254


@dataclass(frozen=True)
class Email:
    """Email address value object (spec §7.2.2 / §10.7).

    Args:
        value: The raw email address.

    :raises DomainValidationError: If longer than ``EMAIL_MAX_LENGTH`` or it fails ``EMAIL_REGEX``.
    """

    value: str

    def __post_init__(self) -> None:
        """Validate length and format.

        :raises DomainValidationError: If too long or malformed.
        """
        if len(self.value) > EMAIL_MAX_LENGTH:
            raise DomainValidationError(
                f"Email: length > {EMAIL_MAX_LENGTH}", field="email", reason="too_long"
            )
        if not EMAIL_REGEX.match(self.value):
            raise DomainValidationError(
                "Email: invalid format", field="email", reason="invalid_format"
            )

"""A number of tokens."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True, order=True)
class TokenCount:
    """A non-negative number of tokens. Ordered, so spend compares against a ceiling directly.

    :param value: The count.
    """

    value: int

    def __post_init__(self) -> None:
        # Reported by a provider or summed by a repository, never sent by the caller — a negative
        # value is a defect, so `field` stays None.
        if self.value < 0:
            raise DomainValidationError("TokenCount must not be negative")

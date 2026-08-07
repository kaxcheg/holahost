"""Resource owner identity, taken from the validated JWT `sub` claim."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OwnerSubject:
    """The `sub` of the token that owns a resource — never taken from the request body (spec §4.1).

    Equality is exact value match (dataclass default), matching the spec's
    stated "exact match" comparison rule.

    :param value: The subject string.
    """

    value: str

    def __post_init__(self) -> None:
        # Comes from an already-validated JWT `sub` claim, not request body
        # data the caller could fix by resubmitting — an empty value here
        # means an upstream token-issuing defect, not a client mistake, so
        # this raises plain ValueError, not DomainValidationError.
        if not self.value.strip():
            raise ValueError("OwnerSubject must not be empty")

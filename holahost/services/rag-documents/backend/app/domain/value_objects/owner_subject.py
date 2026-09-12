"""Resource owner identity, taken from the validated JWT `sub` claim."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class OwnerSubject:
    """The `sub` of the token that owns a resource — never taken from the request body.

    Equality is exact value match (the dataclass default): ownership is decided by
    comparing subjects literally, with no normalisation.

    :param value: The subject string.
    """

    value: str

    def __post_init__(self) -> None:
        # Comes from an already-validated JWT `sub` claim, not request body data the
        # caller could fix by resubmitting — an empty value here means an upstream
        # token-issuing defect, not a client mistake, so `field` stays None and no use
        # case translates it into a 4xx.
        if not self.value.strip():
            raise DomainValidationError("OwnerSubject must not be empty")

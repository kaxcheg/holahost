"""The calling client's identity."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class ClientId:
    """The `client_id` claim of the caller's token — never taken from the request body.

    :param value: The client identifier.
    """

    value: str

    def __post_init__(self) -> None:
        # Comes from an already-validated token: an empty value is an upstream defect the caller
        # cannot fix by resending, so `field` stays None.
        if not self.value.strip():
            raise DomainValidationError("ClientId must not be empty")

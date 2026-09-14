"""The token subject."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class Subject:
    """The `sub` claim of the caller's token; for an s2s token it equals `client_id`.

    :param value: The subject.
    """

    value: str

    def __post_init__(self) -> None:
        # Comes from an already-validated token — `field` stays None, as for `ClientId`.
        if not self.value.strip():
            raise DomainValidationError("Subject must not be empty")

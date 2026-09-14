"""One message of the conversation."""

from __future__ import annotations

from dataclasses import dataclass

from domain.exceptions import DomainValidationError
from domain.value_objects.role import Role


@dataclass(frozen=True, slots=True)
class Message:
    """One message, passed to the provider exactly as the caller sent it.

    :param role: The author.
    :param text: Must contain non-whitespace text; stored unchanged — the service rewrites no
        content.
    """

    role: Role
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise DomainValidationError("Message text must not be empty", field="messages")

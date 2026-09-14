"""Domain-layer exceptions."""

from __future__ import annotations


class DomainValidationError(ValueError):
    """An invariant of a value object or entity was violated — the single type `domain/` raises.

    `field` names the request field a violation traces back to (`messages`, `idempotency_key`), or
    is `None` when nothing the caller sent could have caused it: a value from the validated token,
    the provider registry or a provider's response, or an illegal state transition. Who translates
    it, how a defect is answered and when a subclass is added is the platform's contract — the
    framework specification, "Brief: domain exceptions".

    :param message: Names the violated invariant, never the offending value — a message's text is
        part of a prompt and must not reach the log.
    :param field: The request field this violation traces back to, or `None`.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field

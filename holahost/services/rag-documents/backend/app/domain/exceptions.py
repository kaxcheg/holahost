"""Domain-layer exceptions."""

from __future__ import annotations


class DomainValidationError(ValueError):
    """A value/entity invariant was violated by data traceable to the caller.

    Carries `field` so the interface layer can build the AC-required
    field-indicating response detail (US-R01) without re-deriving which
    input caused the failure. Raised only where the failure is something the
    caller could plausibly fix by resubmitting different data — invariant
    violations that represent an internal defect (parser/chunker/embedder
    bug, or data that should already be guaranteed correct by an earlier
    pipeline stage) raise a plain `ValueError` instead, deliberately not this
    type, so the interface layer's generic handler turns them into a 500
    rather than a 4xx (a type exists only if the caller reacts differently).

    :param message: Human-readable description of the violation.
    :param field: The field name this violation traces back to, if any.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field

"""Domain-layer exceptions."""

from __future__ import annotations


class DomainValidationError(ValueError):
    """An invariant of a value object or entity was violated — the single type `domain/` raises.

    `field` says which kind of violation it is, and it is read rather than assumed:

    - **set** — the violation traces back to a request field. The use case that knows which one
      translates it into a published error and names the field from `field` rather than
      re-deriving it.
    - **`None`** — nothing the caller sent could have caused it: a defect. Nothing translates
      it; `interface/http/errors.py` lists this type in `SILENT_500_TYPES`, so it is answered
      `500 InternalError` with an empty body and its reason in the log.

    A subclass is added only when one call can raise this type for more than one reason and the
    caller has to select one of them: selecting on a `field` string is a comparison no type
    checker sees. Not a `PlatformError` — the domain knows nothing of HTTP.

    :param message: Names the violated invariant. Server-side only: it reaches the log, never a
        response body.
    :param field: The request field this violation traces back to, or `None`.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field

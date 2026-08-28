"""Domain-layer exceptions."""

from __future__ import annotations


class DomainValidationError(ValueError):
    """A value's, entity's or application-layer transit type's invariant was violated.

    The single type for every invariant violation raised by `domain/` and by the
    application-layer value types modelled on it (`SimilarityScore`, `TextFragment`).
    A bare `ValueError` used to carry the internal-defect half of that, turned into
    `ApplicationError` by a `wrap_value_error` decorator sitting on each use case —
    implicit twice over: easy to leave off a new use case, and, since this class *is* a
    `ValueError`, it also swallowed any client-fixable violation a use case had not
    explicitly caught, answering `500` where §7.6 says `422`.

    `field` says which of the two a violation is, and it is read rather than assumed:

    - **set** — the violation traces back to something the caller supplied. The use case
      that knows which request field that was translates it into the matching §7.6 error
      (`InvalidPayloadError`, `UnsupportedMediaTypeError`, `TooManyChunksError`) and
      uses `field` to say which field, without re-deriving it (US-R01).
    - **`None`** — nothing the caller sent could have caused it: a parser, chunker or
      embedder produced a value that violates an invariant, or a pipeline stage that was
      supposed to have guaranteed it did not. No use case translates these; the interface
      layer answers `500 InternalError` with the reason in the log and nothing in the body
      (`interface/http/errors.py`).

    A **subclass** is added when a single call can raise more than one of these and the
    caller has to tell them apart — `ChunkCountExceededError` below is the only one
    today. Where a `try` wraps one construction that can only fail its own way
    (`DocumentName`, `MimeType`), there is nothing to select between and the base type
    with a `field` is the whole contract, so no subclass is warranted (CLAUDE.md: a type
    exists exactly when the calling code reacts to it differently).

    Still a `ValueError` subclass — the stdlib's own name for this fact, and with the
    decorator gone nothing in this service catches `ValueError` any more, so the
    inheritance no longer creates the trap it used to.

    :param message: Human-readable description of the violation. Server-side only: it
        names internal invariants, so it reaches the log and never a response body.
    :param field: The request field this violation traces back to, or `None` when it
        traces back to none.
    """

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class ChunkCountExceededError(DomainValidationError):
    """A document was given more chunks than `MAX_CHUNKS_PER_DOCUMENT` allows.

    Its own type rather than a `field` value to compare against. `Document.create` and
    `replace_content` raise `DomainValidationError` for three invariants, and only this
    one is the caller's to fix (US-R01: `422 TooManyChunksError`) — so the use case has
    to select exactly it and let the other two through to the `500` they deserve.
    Selecting on `field == "chunk_count"` put that decision in a string comparison: no
    type checker can see it, and it silently stops matching the day the field is renamed
    — at which point an internal defect starts being answered as the caller's mistake.

    Carries `field` anyway, per the base class's convention: it is a client-facing
    violation, and the field is what it traces back to.

    :param limit: The ceiling that was exceeded, quoted in the message.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(f"Document chunk_count exceeds {limit}", field="chunk_count")

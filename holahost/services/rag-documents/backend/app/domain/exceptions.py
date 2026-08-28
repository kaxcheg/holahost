"""Domain-layer exceptions."""

from __future__ import annotations


class DomainValidationError(ValueError):
    """A value's, entity's or application-layer transit type's invariant was violated.

    The single type for every invariant violation raised by `domain/` and by the
    application-layer value types modelled on it (`SimilarityScore`, `TextFragment`).

    `field` says which kind of violation it is, and it is read rather than assumed:

    - **set** — traces back to something the caller supplied. The use case that knows
      which request field that was translates it into the matching §7.6 error
      (`InvalidPayloadError`, `UnsupportedMediaTypeError`, `TooManyChunksError`) and uses
      `field` to name it without re-deriving it (US-R01).
    - **`None`** — nothing the caller sent could have caused it: a parser, chunker or
      embedder produced a value violating an invariant, or a stage that was supposed to
      guarantee one did not. No use case translates these; the interface layer answers
      `500 InternalError` with the reason in the log and nothing in the body.

    A **subclass** is added when one call can raise more than one of these and the caller
    has to tell them apart — `ChunkCountExceededError` is the only one today. Where a
    `try` wraps a construction that can fail only its own way (`DocumentName`, `MimeType`)
    there is nothing to select between, so the base type carries the whole contract.

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

    Its own type rather than a `field` value to compare against: `Document.create` and
    `replace_content` raise `DomainValidationError` for three invariants, and only this
    one is the caller's to fix (US-R01: `422 TooManyChunksError`), so the use case must
    select exactly it and let the other two reach the `500` they deserve. Selecting on
    `field == "chunk_count"` would put that in a string comparison no type checker sees.

    Carries `field` anyway, per the base class's convention.

    :param limit: The ceiling that was exceeded, quoted in the message.
    """

    def __init__(self, limit: int) -> None:
        super().__init__(f"Document chunk_count exceeds {limit}", field="chunk_count")

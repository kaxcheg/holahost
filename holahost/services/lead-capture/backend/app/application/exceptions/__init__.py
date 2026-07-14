from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TypedDict

from domain.exceptions import DomainValidationError


class ApplicationError(Exception):
    """Base for all application-layer errors (spec §8.4; taxonomy §10.8).

    Subclasses set a stable ``code`` (wire error code, §10.8) and may override
    :meth:`details_dict` to expose a fixed, per-code ``details`` payload. The interface
    layer maps ``code`` → HTTP status and serializes ``details_dict()`` into the error
    envelope (§5.8 / §10.8).
    """

    code: str = "ERR_INTERNAL"

    def details_dict(self) -> Mapping[str, object]:
        """Return the ``details`` payload for the error envelope (§10.8).

        Overrides return a precise ``TypedDict`` (the single source the OpenAPI exporter derives the
        per-code ``details`` schema from, §11.3); the base return widens to ``Mapping[str, object]`` so
        a ``TypedDict`` is a valid covariant override.

        Returns:
            Per-code detail keys; empty by default. ``ERR_INTERNAL``'s ``request_id`` is
            injected by the interface layer (§10.8), not here.
        """
        return {}


class InvalidMagicLinkError(ApplicationError):
    """Magic link missing/expired/unknown (§9.8) → 401 ERR_INVALID_MAGIC_LINK."""

    code = "ERR_INVALID_MAGIC_LINK"


class InvalidApiKeyError(ApplicationError):
    """Upstream 401 on a BYOK key (§9.5 / §9.8) → 401 ERR_INVALID_API_KEY."""

    code = "ERR_INVALID_API_KEY"


class NotFoundDetails(TypedDict):
    """``details`` for ``ERR_NOT_FOUND`` (§10.8)."""

    resource: str


class NotFoundError(ApplicationError):
    """Requested resource not found (§10.3 / §10.8) → 404 ERR_NOT_FOUND."""

    code = "ERR_NOT_FOUND"

    def __init__(self, resource: str, message: str = "") -> None:
        """Init.

        Args:
            resource: Resource kind, e.g. ``"guidebook"`` / ``"lead"`` (§10.8 details).
            message: Optional technical message (sanitized before reaching the client).
        """
        super().__init__(message)
        self.resource = resource

    def details_dict(self) -> NotFoundDetails:
        return {"resource": self.resource}


class InvalidPayloadDetails(TypedDict):
    """``details`` for ``ERR_INVALID_PAYLOAD`` (§10.8); ``field``/``reason`` may be null."""

    field: str | None
    reason: str | None


class InvalidPayloadError(ApplicationError):
    """Generic invalid request payload (§8.4 / §9.0) → 422 ERR_INVALID_PAYLOAD.

    Raised when a VO/entity factory raises ``DomainValidationError`` (via ``payload_validation()``,
    §9.0) or by the interface layer on a shape/contract violation (``reason="invalid_json"``,
    §10.8); ``field`` / ``reason`` feed the §10.8 ``details`` payload. (Renamed from the legacy
    ``ERR_INVALID_TEMPLATE`` — the template flow was removed in §10.6; this is the generic
    payload-validation code.)
    """

    code = "ERR_INVALID_PAYLOAD"

    def __init__(
        self,
        message: str = "",
        *,
        field: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Init.

        Args:
            message: Technical message kept for ``details.field`` mapping (§9.0); sanitized
                in the envelope before reaching the client.
            field: Offending field name from §10.6, or None.
            reason: One of empty|too_long|contacts_no_phone|invalid_format|invalid_json, or None.
        """
        super().__init__(message)
        self.field = field
        self.reason = reason

    def details_dict(self) -> InvalidPayloadDetails:
        return {"field": self.field, "reason": self.reason}


class NoGuidebookAttachedError(ApplicationError):
    """Lead has no guidebook (§9.5 / §9.8) → 409 ERR_NO_GUIDEBOOK."""

    code = "ERR_NO_GUIDEBOOK"


class EmailConflictError(ApplicationError):
    """New-email ``UNIQUE(email)`` race lost (§4.1) → 409 ERR_EMAIL_CONFLICT.

    Raised only by ``PostgresLeadsRepo.add`` when two transactions both insert the *same new*
    email concurrently (both saw ``existing is None`` under READ COMMITTED; the loser hits
    ``UNIQUE(email)``). The client retries, taking the silent-upsert/update path (§4.1). The email
    is carried for server-side logging only and is deliberately NOT exposed in ``details`` (PII;
    ``details_dict()`` stays ``{}``).
    """

    code = "ERR_EMAIL_CONFLICT"

    def __init__(self, email: str, message: str = "") -> None:
        """Init.

        Args:
            email: The conflicting email (server-side logging only; not surfaced to the client).
            message: Optional technical message.
        """
        super().__init__(message)
        self.email = email


class PayloadTooLargeDetails(TypedDict):
    """``details`` for ``ERR_PAYLOAD_TOO_LARGE`` (§10.8)."""

    max_bytes: int


class PayloadTooLargeError(ApplicationError):
    """Uploaded file over the byte-size limit (§9.4 / §9.8) → 413 ERR_PAYLOAD_TOO_LARGE."""

    code = "ERR_PAYLOAD_TOO_LARGE"

    def __init__(self, max_bytes: int, message: str = "") -> None:
        """Init.

        Args:
            max_bytes: The exceeded byte limit reported to the UI (§10.8 details).
            message: Optional technical message.
        """
        super().__init__(message)
        self.max_bytes = max_bytes

    def details_dict(self) -> PayloadTooLargeDetails:
        return {"max_bytes": self.max_bytes}


class TooManyChunksDetails(TypedDict):
    """``details`` for ``ERR_TOO_MANY_CHUNKS`` (§10.8)."""

    max_chunks: int


class TooManyChunksError(ApplicationError):
    """Parsed document yields more than the chunk cap (§9.4 / §9.8) → 413 ERR_TOO_MANY_CHUNKS.

    Distinct from ``PayloadTooLargeError``: the byte size may be fine, but the chunk count exceeds
    the per-guidebook cap (memory / embedding-count bound). Carries the chunk limit, not bytes.
    """

    code = "ERR_TOO_MANY_CHUNKS"

    def __init__(self, max_chunks: int, message: str = "") -> None:
        """Init.

        Args:
            max_chunks: The exceeded chunk-count cap reported to the UI (§10.8 details).
            message: Optional technical message.
        """
        super().__init__(message)
        self.max_chunks = max_chunks

    def details_dict(self) -> TooManyChunksDetails:
        return {"max_chunks": self.max_chunks}


class UnsupportedMediaTypeDetails(TypedDict):
    """``details`` for ``ERR_UNSUPPORTED_MEDIA_TYPE`` (§10.8)."""

    allowed: list[str]


class UnsupportedMediaTypeError(ApplicationError):
    """Unsupported MIME type (§9.4 / §9.8) → 415 ERR_UNSUPPORTED_MEDIA_TYPE."""

    code = "ERR_UNSUPPORTED_MEDIA_TYPE"

    def __init__(self, allowed: list[str], message: str = "") -> None:
        """Init.

        Args:
            allowed: Allowed MIME types shown to the UI (§10.8 details).
            message: Optional technical message.
        """
        super().__init__(message)
        self.allowed = allowed

    def details_dict(self) -> UnsupportedMediaTypeDetails:
        return {"allowed": self.allowed}


class EmptyDocumentError(ApplicationError):
    """Extracted text below the minimum (§9.4 / §9.8) → 422 ERR_EMPTY_DOCUMENT."""

    code = "ERR_EMPTY_DOCUMENT"


class RateLimitDetails(TypedDict):
    """``details`` for ``ERR_RATE_LIMIT`` (§10.8); ``retry_after_s`` is seconds."""

    scope: str
    retry_after_s: int


class RateLimitExceededError(ApplicationError):
    """Per-window rate cap exceeded (§8.2.8 / §9.8) → 429 ERR_RATE_LIMIT.

    Raised by the ``RateLimiter`` implementation. ``scope`` is the string value
    ("ip" / "magic_link", §4.4); the wire ``details`` key is ``retry_after_s`` (§10.8).
    """

    code = "ERR_RATE_LIMIT"

    def __init__(self, scope: str, retry_after_seconds: int, message: str = "") -> None:
        """Init.

        Args:
            scope: ``"ip"`` or ``"magic_link"`` (rate_limit_counters.scope, §4.4).
            retry_after_seconds: Seconds until the window resets.
            message: Optional technical message.
        """
        super().__init__(message)
        self.scope = scope
        self.retry_after_seconds = retry_after_seconds

    def details_dict(self) -> RateLimitDetails:
        return {"scope": self.scope, "retry_after_s": self.retry_after_seconds}


class SampleBudgetExhaustedDetails(TypedDict):
    """``details`` for ``ERR_SAMPLE_BUDGET_EXHAUSTED`` (§10.8); ISO-8601 UTC reset instant."""

    reset_at: str


class SampleBudgetExhaustedError(ApplicationError):
    """Daily sample token cap reached (§9.1 / §9.8) → 429 ERR_SAMPLE_BUDGET_EXHAUSTED."""

    code = "ERR_SAMPLE_BUDGET_EXHAUSTED"

    def __init__(self, reset_at: str, message: str = "") -> None:
        """Init.

        Args:
            reset_at: ISO-8601 UTC instant when the budget resets (§10.8 details).
            message: Optional technical message.
        """
        super().__init__(message)
        self.reset_at = reset_at

    def details_dict(self) -> SampleBudgetExhaustedDetails:
        return {"reset_at": self.reset_at}


class UpstreamLLMDetails(TypedDict):
    """``details`` for ``ERR_UPSTREAM_LLM`` (§10.8); ``retryable`` drives client backoff."""

    upstream_status: int | None
    retryable: bool


class UpstreamLLMError(ApplicationError):
    """LLM upstream failure (§9.1 / §9.5 / §9.8) → 502 ERR_UPSTREAM_LLM."""

    code = "ERR_UPSTREAM_LLM"

    def __init__(
        self,
        retryable: bool,
        upstream_status: int | None = None,
        message: str = "",
    ) -> None:
        """Init.

        Args:
            retryable: True for upstream 5xx/429 (§10.8); drives client backoff.
            upstream_status: Upstream HTTP status, if known.
            message: Optional technical message.
        """
        super().__init__(message)
        self.upstream_status = upstream_status
        self.retryable = retryable

    def details_dict(self) -> UpstreamLLMDetails:
        return {"upstream_status": self.upstream_status, "retryable": self.retryable}


class UpstreamEmailDetails(TypedDict):
    """``details`` for ``ERR_UPSTREAM_EMAIL`` (§10.8); ``retryable`` drives client backoff."""

    retryable: bool


class UpstreamEmailError(ApplicationError):
    """Email-provider failure (§9.2 / §9.8) → 502 ERR_UPSTREAM_EMAIL."""

    code = "ERR_UPSTREAM_EMAIL"

    def __init__(self, retryable: bool, message: str = "") -> None:
        """Init.

        Args:
            retryable: True for retryable upstream failures (§10.8).
            message: Optional technical message.
        """
        super().__init__(message)
        self.retryable = retryable

    def details_dict(self) -> UpstreamEmailDetails:
        return {"retryable": self.retryable}


@contextmanager
def payload_validation() -> Iterator[None]:
    """Convert ``DomainValidationError`` from VO/entity factories into ``InvalidPayloadError``.

    Wrap each ``primitive -> VO`` / entity-factory block in a use case with this manager so a bad
    primitive surfaces as 422 ``ERR_INVALID_PAYLOAD`` (spec §9.0) instead of leaking to the
    handler's ``except Exception`` (500). The ``field`` / ``reason`` carried by the
    ``DomainValidationError`` flow through to the §10.8 ``details`` payload.

    Only ``DomainValidationError`` is caught: every payload-facing VO/entity factory raises it
    (domain invariant, §8.0), so a *plain* ``ValueError`` escaping this block signals an
    unconverted internal bug and is left to propagate (500), not silently masked as a client 422.

    :raises InvalidPayloadError: if the wrapped block raises ``DomainValidationError``.
    """
    try:
        yield
    except DomainValidationError as e:
        raise InvalidPayloadError(str(e), field=e.field, reason=e.reason) from e


@contextmanager
def magic_link_validation() -> Iterator[None]:
    """Convert a ``MagicLink`` VO failure into ``InvalidMagicLinkError`` (spec §9.8) → 401.

    An empty/malformed magic-link token is an invalid credential — not a client-payload field error
    (422 via :func:`payload_validation`) nor an internal bug (500). Wrap the ``MagicLink(...)``
    construction in a use case with this manager so a bad token surfaces as 401
    ``ERR_INVALID_MAGIC_LINK``, consistent with the unknown/expired cases. Keep the wrapped block to
    that single construction so the broad ``except ValueError`` cannot catch an unrelated error.

    :raises InvalidMagicLinkError: if the wrapped block raises ``ValueError``.
    """
    try:
        yield
    except ValueError as e:
        raise InvalidMagicLinkError() from e

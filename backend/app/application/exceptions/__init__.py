from __future__ import annotations


class ApplicationError(Exception):
    """Base for all application-layer errors (spec §8.4; taxonomy §10.8).

    Subclasses set a stable ``code`` (wire error code, §10.8) and may override
    :meth:`details_dict` to expose a fixed, per-code ``details`` payload. The interface
    layer maps ``code`` → HTTP status and serializes ``details_dict()`` into the error
    envelope (§5.8 / §10.8).
    """

    code: str = "ERR_INTERNAL"

    def details_dict(self) -> dict[str, object]:
        """Return the ``details`` payload for the error envelope (§10.8).

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

    def details_dict(self) -> dict[str, object]:
        return {"resource": self.resource}


class InvalidPayloadError(ApplicationError):
    """Invalid primitive / template field (§8.4 / §9.0) → 422 ERR_INVALID_TEMPLATE.

    Raised when a VO/entity factory raises ``ValueError`` (via ``payload_validation()``,
    added in B-20 / §9.0); ``field`` / ``reason`` feed the §10.8 ``details`` payload.
    """

    code = "ERR_INVALID_TEMPLATE"

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
            reason: One of empty|too_long|contacts_no_phone|invalid_format|honeypot, or None.
        """
        super().__init__(message)
        self.field = field
        self.reason = reason

    def details_dict(self) -> dict[str, object]:
        return {"field": self.field, "reason": self.reason}


class NoGuidebookAttachedError(ApplicationError):
    """Lead has no guidebook (§9.5 / §9.8) → 409 ERR_NO_GUIDEBOOK."""

    code = "ERR_NO_GUIDEBOOK"


class PayloadTooLargeError(ApplicationError):
    """Upload / chunk-count over the limit (§9.4 / §9.8) → 413 ERR_PAYLOAD_TOO_LARGE."""

    code = "ERR_PAYLOAD_TOO_LARGE"

    def __init__(self, max_bytes: int, message: str = "") -> None:
        """Init.

        Args:
            max_bytes: The exceeded limit reported to the UI (§10.8 details).
            message: Optional technical message.
        """
        super().__init__(message)
        self.max_bytes = max_bytes

    def details_dict(self) -> dict[str, object]:
        return {"max_bytes": self.max_bytes}


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

    def details_dict(self) -> dict[str, object]:
        return {"allowed": self.allowed}


class EmptyDocumentError(ApplicationError):
    """Extracted text below the minimum (§9.4 / §9.8) → 422 ERR_EMPTY_DOCUMENT."""

    code = "ERR_EMPTY_DOCUMENT"


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

    def details_dict(self) -> dict[str, object]:
        return {"scope": self.scope, "retry_after_s": self.retry_after_seconds}


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

    def details_dict(self) -> dict[str, object]:
        return {"reset_at": self.reset_at}


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

    def details_dict(self) -> dict[str, object]:
        return {"upstream_status": self.upstream_status, "retryable": self.retryable}


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

    def details_dict(self) -> dict[str, object]:
        return {"retryable": self.retryable}

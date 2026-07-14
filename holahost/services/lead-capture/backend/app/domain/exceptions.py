from __future__ import annotations


class DomainValidationError(ValueError):
    """A client-payload validation error carrying structured error context (spec §7 / §9.0).

    The exception *type* encodes the HTTP mapping (§9.8):

    - **Client-submitted** values (``Email`` / ``LeadFlow`` / ``GuidebookName`` / ``GuestMessage`` /
      ``MagicLink``) raise this; ``payload_validation()`` — which catches *only*
      ``DomainValidationError`` — converts it to 422 ``ERR_INVALID_PAYLOAD`` with ``field`` /
      ``reason`` in the §10.8 ``details``.
    - **Internal invariants** built by business logic / server (``Embedding`` from model output,
      ``IpHash`` from ``sha256(ip || salt)``) raise a *plain* ``ValueError`` instead — never this —
      and are constructed outside ``payload_validation()``, so they propagate to the interface's
      catch-all → 500. They are our bugs, not the client's payload.

    Subclassing ``ValueError`` keeps it compatible with generic ``except ValueError`` handling; the
    use case always converts it via ``payload_validation()`` before it can reach the interface, so
    the 422/500 split is unambiguous. ``field`` / ``reason`` are optional.

    Args:
        message: Technical message (sanitized before reaching the client).
        field: Offending field name (§10.6 / §10.8), or None.
        reason: Stable reason code (e.g. ``"empty"`` / ``"too_long"``, §10.8), or None.
    """

    def __init__(
        self, message: str = "", *, field: str | None = None, reason: str | None = None
    ) -> None:
        super().__init__(message)
        self.field = field
        self.reason = reason

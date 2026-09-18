"""Exceptions raised by this service's ports.

The three storage failures are the platform's — same types, same split by reaction, one translation
point from vendor errors — so they are re-exported from `holahost-db` rather than redeclared.

The provider's own are split the same way, by what the use case does next rather than by what the
vendor said: repeat it, move to the next candidate model, or record the spend and refuse. None of
them is a `PlatformError`: they never reach the wire themselves.
"""

from __future__ import annotations

from holahost_db import ConcurrentUpdateError, IntegrityError, StorageUnavailableError

from domain.value_objects.usage import Usage

__all__ = [
    "ConcurrentUpdateError",
    "IntegrityError",
    "ProviderRefusedContentError",
    "ProviderRejectedRequestError",
    "StorageUnavailableError",
    "TransientProviderError",
]


class TransientProviderError(Exception):
    """The provider failed in a way a repeat may get past: `429`, a `5xx`, overload, a timeout.

    The message is server-side only — it reaches the log, never a response — and carries no request
    content.

    :param message: What happened, for the log.
    :param status: The vendor's HTTP status; `None` for a timeout, which has none.
    :param retry_after: The vendor's `Retry-After` in seconds, when it sent one.
    """

    def __init__(self, message: str, *, status: int | None, retry_after: float | None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class ProviderRejectedRequestError(Exception):
    """The vendor refused the request itself: a revoked key, an unknown model, a malformed call.

    The cause is on this service's side and specific to that vendor — its key, its adapter, its
    model list — so repeating at the same vendor is pointless while another candidate may still
    answer. When none does, it is a defect and is answered `500`.

    :param message: What happened, for the log; no request content.
    :param status: The vendor's HTTP status, when there was one.
    """

    def __init__(self, message: str, *, status: int | None) -> None:
        super().__init__(message)
        self.status = status


class ProviderRefusedContentError(Exception):
    """The model declined to answer this content.

    The call succeeded as far as billing goes, so it carries the usage the provider confirmed: the
    spend is recorded even though no answer is returned. Another vendor is not tried — the cause is
    the content, not the vendor.

    :param usage: The provider's own figures for the refused call.
    """

    def __init__(self, *, usage: Usage) -> None:
        super().__init__("the provider refused to generate for this content")
        self.usage = usage

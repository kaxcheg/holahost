"""What can go wrong in a command, sorted by what the operator does about it.

A type exists only where the reaction differs — each has its own exit code (`cli.EXIT_CODES`).
`code` is what the operator and a script see: the service's own code when one came back (its class
name on the wire, e.g. `UploadTooLargeError`), otherwise this class's name. That is the services'
convention too, so any code greps back to the class that produced it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


class GuestReplyError(Exception):
    """Base of every failure a command reports."""

    def __init__(
        self, message: str, *, code: str | None = None, details: Mapping[str, object] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or type(self).__name__
        self.details: dict[str, object] = dict(details or {})
        # Set by the one-shot when deleting its temporary document failed too.
        self.cleanup_failure: CleanupFailure | None = None


@dataclass(frozen=True)
class CleanupFailure:
    """The one-shot's temporary document outlived the command: deleting it failed."""

    document_id: str
    error: GuestReplyError


class ConfigurationError(GuestReplyError):
    """A variable is unset or invalid; raised before any network call."""


class FileUnreadableError(GuestReplyError):
    """The file does not exist or cannot be read; raised before any network call."""


class DocumentNotFoundError(GuestReplyError):
    """`404 NotFoundError`: no such document — or another subject's, which looks the same."""


class RequestRejectedError(GuestReplyError):
    """A service refused what was sent — the file, the message, the model alias."""


class LimitReachedError(GuestReplyError):
    """A limit refused the call: a rate limit not worth waiting out any longer, or a budget."""


class ProviderUnavailableError(GuestReplyError):
    """`llm-client` got no answer from any provider (`502 UpstreamLlmError`); it already retried."""


class TokenRejectedError(GuestReplyError):
    """A service refused the token (`401`): expired, or not signed for this stack."""


class ServiceUnreachableError(GuestReplyError):
    """No usable answer: no connection, a timeout, or a service unable to validate tokens (503)."""


class UnexpectedResponseError(GuestReplyError):
    """An answer outside the published contract: `500`, an unknown status, a malformed body."""

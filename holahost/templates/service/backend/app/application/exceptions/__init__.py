"""The errors this service throws at its boundary — one class per error.

Each class is the whole contract for the error it names: its **identity** on the wire is
its class name, verbatim (`PlatformError.code`), and the shape of its **`details`** is what
`details_dict()` returns. Nothing else is contractual — the `message` is for a person
reading a log, and the HTTP status is a projection applied by `interface/http/errors.py`,
which is why two errors may share one status and why changing a status is not a change to
this file.

No two errors share an identity: a consumer builds its message from `details`, so what the
identity has to name is which error the service threw, not the category it falls in.

Three of the errors below are re-exported rather than declared: every service rejects a
field, refuses a request that broke the transport contract, and answers for a resource that
is absent or another subject's — with the same identity and the same `details` each time.
"""

from __future__ import annotations

from holahost_http import (
    InvalidPayloadError,
    MalformedRequestError,
    NotFoundError,
    PlatformError,
)

__all__ = [
    "ApplicationError",
    "InvalidPayloadError",
    "MalformedRequestError",
    "NotFoundError",
]


class ApplicationError(PlatformError):
    """Base for every application-layer, HTTP-facing exception of this service.

    Inherits the platform base for the envelope contract it defines (`code` +
    `details_dict()`); the errors below stay this service's own.

    Never thrown itself, and deliberately absent from the interface layer's status table:
    an instance of the base, or of a subclass nobody published, is by construction not one
    of this service's errors and is answered `500 InternalError` with an empty body.
    """


# One class per error the service can answer with. Give each a `details_dict()` where it
# has a payload, and keep the key set fixed per identity — `None` for "not applicable"
# rather than an absent key, so a consumer never has to know which raise site answered:
#
# class SomethingTooLargeError(ApplicationError):
#     def __init__(self, limit: int, actual: int) -> None:
#         super().__init__("something too large")
#         self.limit = limit
#         self.actual = actual
#
#     def details_dict(self) -> Mapping[str, object]:   # from collections.abc
#         return {"limit": self.limit, "actual": self.actual}

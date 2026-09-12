"""Exceptions raised by holahost-auth."""


class AuthenticationError(Exception):
    """A JWT failed validation, for any reason.

    Every failure mode below maps to the same HTTP reaction — 401 with no
    reason disclosed in the response body — so one type is correct: a type
    exists only where the caller reacts differently. `reason` is for logging
    only, never for the response body.

    :param reason: Human-readable cause, logged by the caller.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JwksUnavailableError(Exception):
    """The JWKS endpoint could not be reached or returned an unusable response.

    Kept distinct from `AuthenticationError`: a JWKS outage/misconfiguration
    is an infrastructure failure that would reject *every* otherwise-valid
    token, not a per-request validation failure — it must not be reported to
    callers as "invalid credentials" (401), which would mask a real incident
    as what looks like a wave of bad tokens. Maps to 503, not 401.

    :param reason: Human-readable cause, logged by the caller.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason

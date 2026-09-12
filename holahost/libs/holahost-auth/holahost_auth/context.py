"""Authenticated request context populated by holahost-auth."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TokenContext:
    """Identity and delegation facts extracted from a validated JWT.

    :param subject: The ``sub`` claim.
    :param client_id: The ``client_id`` claim identifying the calling client.
    :param roles: Global roles from the token (empty for pure service tokens).
    :param act: The delegating service's subject (RFC 8693 ``act.sub``) if this
        is a token-exchange (on-behalf-of-user) token, else ``None``. Multi-hop
        nesting is out of scope.
    """

    subject: str
    client_id: str
    roles: tuple[str, ...]
    act: str | None

    @property
    def is_service_token(self) -> bool:
        """True for a service (client_credentials) token — no user context."""
        return self.subject == self.client_id

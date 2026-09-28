"""The credential every call carries.

One source today: a ready-made token minted by the dev minter, from `HOLAHOST_TOKEN`. When `auth`
exists, `client_credentials` replaces it here and nowhere else — and brings the one token re-request
on a `401` with it, which a static token has no use for: re-reading it sends the same token again.
"""

from __future__ import annotations

from pydantic import SecretStr


class StaticToken:
    """A ready-made token, sent as is on every call of the command."""

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    def authorization(self) -> str:
        """The `Authorization` header's value — the one place the token is unwrapped."""
        return f"Bearer {self._token.get_secret_value()}"

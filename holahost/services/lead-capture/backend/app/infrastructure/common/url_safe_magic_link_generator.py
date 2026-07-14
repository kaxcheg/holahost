from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from pydantic import SecretStr

from domain.value_objects.magic_link import MagicLink


class UrlSafeMagicLinkGenerator:
    """Generate opaque URL-safe magic-link tokens via :func:`secrets.token_urlsafe` (spec §10.3).

    Satisfies the ``MagicLinkGenerator`` port structurally. ``token_bytes`` is the entropy in bytes
    (``settings.magic_link_token_bytes``), NOT the output string length.
    """

    def __init__(self, token_bytes: int) -> None:
        if token_bytes <= 0:
            raise ValueError("UrlSafeMagicLinkGenerator: token_bytes must be positive")
        self._token_bytes = token_bytes

    def generate(self) -> MagicLink:
        """Return a fresh :class:`MagicLink` wrapping a url-safe token."""
        return MagicLink(SecretStr(secrets.token_urlsafe(self._token_bytes)))


if TYPE_CHECKING:
    from application.ports.magic_link import MagicLinkGenerator

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: UrlSafeMagicLinkGenerator) -> MagicLinkGenerator:
        return x

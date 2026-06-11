from __future__ import annotations

from typing import Protocol

from domain.value_objects.email import Email
from domain.value_objects.magic_link import MagicLink


class EmailSender(Protocol):
    """Port: deliver the magic-link email (spec §8.2.6)."""

    def send_magic_link(self, to: Email, magic_link: MagicLink) -> None:
        """Send the magic-link email to ``to``.

        Args:
            to: Recipient email.
            magic_link: The magic link to embed in the email URL (impl builds the URL).

        Raises:
            UpstreamEmailError: if the email provider call fails (§9.2 / §9.8).
        """
        ...

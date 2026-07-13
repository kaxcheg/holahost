from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

from application.exceptions import UpstreamEmailError
from domain.value_objects.email import Email
from domain.value_objects.magic_link import MagicLink

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SUBJECT = "Your hola.host guidebook link"


class SmtpEmailSender:
    """Dev-only EmailSender over SMTP (Mailpit) via stdlib smtplib (spec §12.1, C-01).

    Reuses the Resend adapter's magic-link template, delivering to a local Mailpit SMTP server
    instead of Resend (the dev composition root selects it; wiring is B-46). The token (SecretStr)
    is used only to build the URL and never logged. SMTP failures -> ``UpstreamEmailError``.

    Structurally conforms to the EmailSender port (no inheritance): see ``_conforms``.
    """

    def __init__(
        self,
        host: str,
        port: int,
        from_address: str,
        path: str,
    ) -> None:
        """Init.

        Args:
            host: Mailpit SMTP host.
            port: Mailpit SMTP port (e.g. 1025).
            from_address: Sender address.
            path: Magic-link URL prefix the token is appended to — composed by the wiring as
                ``{frontend_origin}{magic_link_path}?{magic_link_url_param}=`` (§10.7, D-21).
        """
        self._host = host
        self._port = port
        self._from = from_address
        self._path = path
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "j2"]),
        )

    def send_magic_link(self, to: Email, magic_link: MagicLink) -> None:
        """Render and send the magic-link email via SMTP (Mailpit; see port).

        :raises UpstreamEmailError: on any SMTP / socket failure (§9.2 / §9.8).
        """
        url = f"{self._path}{magic_link.value.get_secret_value()}"
        html = self._env.get_template("magic_link.html.j2").render(magic_link_url=url)
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to.value
        message["Subject"] = _SUBJECT
        message.set_content("Open this link to access your guidebook.")
        message.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(self._host, self._port) as smtp:
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise UpstreamEmailError(retryable=True, message=str(exc)) from exc


if TYPE_CHECKING:
    from application.ports.email import EmailSender

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: SmtpEmailSender) -> EmailSender:
        return x

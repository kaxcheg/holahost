from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import SecretStr

from application.exceptions import UpstreamEmailError
from domain.value_objects.email import Email
from domain.value_objects.magic_link import MagicLink

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_SUBJECT = "Your hola.host guidebook link"
_RESEND_URL = "https://api.resend.com/emails"


class ResendEmailSender:
    """EmailSender adapter over the Resend REST API via httpx (spec §10.7, port §8.2.6, D5).

    Renders the magic-link email from an autoescaped Jinja2 template and POSTs it to Resend with
    ``Authorization: Bearer <api_key>``. The magic-link token (SecretStr) is used ONLY to build the
    URL and is never logged. Any non-2xx or transport failure -> ``UpstreamEmailError`` (retryable on
    429/5xx/transport, non-retryable on other 4xx).

    Structurally conforms to the EmailSender port (no inheritance): see ``_conforms``.
    """

    def __init__(
        self,
        api_key: SecretStr,
        from_address: str,
        magic_link_base_url: str,
        magic_link_url_param: str,
        timeout_seconds: float,
        client: httpx.Client | None = None,
    ) -> None:
        """Init.

        Args:
            api_key: Resend API key (SecretStr).
            from_address: Verified sender address.
            magic_link_base_url: Base URL the token is appended to (§10.7, D5).
            magic_link_url_param: Query-param name carrying the token: ``{base}/?<param>=<token>``.
            timeout_seconds: Per-request timeout.
            client: Optional injected httpx client (tests pass a MockTransport client).
        """
        self._api_key = api_key
        self._from = from_address
        self._base_url = magic_link_base_url.rstrip("/")
        self._magic_link_url_param = magic_link_url_param
        self._client = client if client is not None else httpx.Client(timeout=timeout_seconds)
        self._env = Environment(
            loader=FileSystemLoader(str(_TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "j2"]),
        )

    def close(self) -> None:
        """Close the underlying httpx client (called by the composition root, B-46)."""
        self._client.close()

    def send_magic_link(self, to: Email, magic_link: MagicLink) -> None:
        """Render and send the magic-link email via Resend (see port).

        :raises UpstreamEmailError: on any non-2xx response or transport failure (§9.2 / §9.8).
        """
        url = f"{self._base_url}/?{self._magic_link_url_param}={magic_link.value.get_secret_value()}"
        html = self._env.get_template("magic_link.html.j2").render(magic_link_url=url)
        payload: dict[str, Any] = {
            "from": self._from,
            "to": [to.value],
            "subject": _SUBJECT,
            "html": html,
        }
        try:
            response = self._client.post(
                _RESEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise UpstreamEmailError(retryable=status == 429 or status >= 500) from exc
        except httpx.HTTPError as exc:
            raise UpstreamEmailError(retryable=True, message=str(exc)) from exc


if TYPE_CHECKING:
    from application.ports.email import EmailSender

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: ResendEmailSender) -> EmailSender:
        return x

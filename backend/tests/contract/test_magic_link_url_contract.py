"""Magic-link URL contract (C-10a, US-03 / spec section 13.3).

The backend composes the email URL prefix
``{frontend_origin}{magic_link_path}?{magic_link_url_param}=`` (``scripts/wiring.py``
``make_email_sender``); the frontend scopes its landing to ``MAGIC_LINK_PATH``. Both values come
from the single source ``frontend/.env`` (D-21, spec section 10.9). This test feeds the real file
values through the real composition and asserts the resulting pathname equals the frontend landing
path up to a trailing slash — guarding against prefix drift (e.g. the legacy ``{origin}/?ml=``
shape) that would silently strand already-delivered emails.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from infrastructure.email.resend_email_sender import ResendEmailSender
from infrastructure.email.smtp_email_sender import SmtpEmailSender
from scripts.wiring import make_email_sender
from tests._support.settings import make_settings

_FRONTEND_ENV = Path(__file__).resolve().parents[3] / "frontend" / ".env"


def _parse_env(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser mirroring the Terraform-side parsing (infra/envs/*/main.tf)."""
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def _strip_trailing_slash(path: str) -> str:
    return path[:-1] if len(path) > 1 and path.endswith("/") else path


class TestMagicLinkUrlContract:
    def test_email_prefix_pathname_matches_frontend_landing_path(self) -> None:
        contract = _parse_env(_FRONTEND_ENV)
        landing_path = contract["MAGIC_LINK_PATH"]
        url_param = contract["MAGIC_LINK_URL_PARAM"]

        settings = make_settings(magic_link_path=landing_path, magic_link_url_param=url_param)
        sender = make_email_sender(settings)
        # Narrow to the concrete adapters holding the composed prefix (precedent: test_wiring.py).
        assert isinstance(sender, SmtpEmailSender | ResendEmailSender)
        prefix = sender._path

        parsed = urlsplit(prefix)
        assert _strip_trailing_slash(parsed.path) == _strip_trailing_slash(landing_path)
        assert parsed.query == f"{url_param}="

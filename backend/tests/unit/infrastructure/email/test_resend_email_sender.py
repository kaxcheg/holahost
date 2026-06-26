from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from application.exceptions import UpstreamEmailError
from domain.value_objects.email import Email
from domain.value_objects.magic_link import MagicLink
from infrastructure.email.resend_email_sender import ResendEmailSender


def _sender(handler: Callable[[httpx.Request], httpx.Response]) -> ResendEmailSender:
    return ResendEmailSender(
        api_key=SecretStr("re_secret"),
        from_address="noreply@hola.host",
        magic_link_base_url="https://app.test/claim",
        timeout_seconds=5.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _send(sender: ResendEmailSender) -> None:
    sender.send_magic_link(Email("guest@example.com"), MagicLink(SecretStr("tok123")))


def test_success_posts_bearer_and_renders_url() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"id": "e1"})

    _send(_sender(handler))
    assert seen["auth"] == "Bearer re_secret"
    assert "https://app.test/claim/tok123" in seen["body"]  # token reaches the URL
    assert "guest@example.com" in seen["body"]


@pytest.mark.parametrize(("status", "retryable"), [(422, False), (429, True), (500, True)])
def test_error_status_maps_to_upstream_email(status: int, retryable: bool) -> None:
    with pytest.raises(UpstreamEmailError) as exc:
        _send(_sender(lambda r: httpx.Response(status, json={})))
    assert exc.value.retryable is retryable


def test_timeout_maps_to_retryable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom")

    with pytest.raises(UpstreamEmailError) as exc:
        _send(_sender(handler))
    assert exc.value.retryable is True

from holahost_auth.context import TokenContext


def test_service_token_when_subject_equals_client_id() -> None:
    ctx = TokenContext(subject="svc-a", client_id="svc-a", roles=(), act=None)
    assert ctx.is_service_token is True


def test_user_token_when_subject_differs_from_client_id() -> None:
    ctx = TokenContext(subject="user-123", client_id="web-guest-portal", roles=("guest",), act=None)
    assert ctx.is_service_token is False

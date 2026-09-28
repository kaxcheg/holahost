"""`mint` prints the token and nothing else; `serve` is the container's command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import jwt
import pytest

from dev_minter.cli import main
from dev_minter.keys import KEY_FILE, load_or_create


@pytest.fixture(autouse=True)
def _served_key(tmp_path: Path) -> None:
    """The key `serve` creates on start — `mint` only reads it."""
    load_or_create(tmp_path)


def _claims(token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(token, options={"verify_signature": False})
    return claims


def test_mint_prints_the_token_alone(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--key-dir", str(tmp_path), "mint"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    claims = _claims(out.strip())
    assert (claims["sub"], claims["aud"]) == ("guest-reply-cli", ["rag-documents", "llm-client"])


def test_mint_takes_another_client(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = ["--key-dir", str(tmp_path), "mint", "--client-id", "chat-assistant-api"]
    main([*argv, "--aud", "rag-documents", "--ttl", "60"])
    claims = _claims(capsys.readouterr().out.strip())
    assert (claims["sub"], claims["client_id"], claims["aud"]) == (
        "chat-assistant-api",
        "chat-assistant-api",
        ["rag-documents"],
    )
    assert claims["exp"] - claims["iat"] == 60


def test_mint_signs_with_the_key_in_the_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["--key-dir", str(tmp_path), "mint"])
    first = jwt.get_unverified_header(capsys.readouterr().out.strip())["kid"]
    main(["--key-dir", str(tmp_path), "mint"])
    assert jwt.get_unverified_header(capsys.readouterr().out.strip())["kid"] == first


def test_mint_never_creates_a_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # A key the running server did not create is one its JWKS does not carry.
    empty = tmp_path / "empty"
    assert main(["--key-dir", str(empty), "mint"]) == 1
    captured = capsys.readouterr()
    assert (captured.out, "make dev-up" in captured.err) == ("", True)
    assert not (empty / KEY_FILE).exists()


@pytest.mark.parametrize("ttl", ["0", "-5", "soon"])
def test_a_lifetime_that_is_not_a_positive_number_is_refused(tmp_path: Path, ttl: str) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--key-dir", str(tmp_path), "mint", "--ttl", ttl])
    assert exit_.value.code == 2


def test_a_command_is_required(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["--key-dir", str(tmp_path)])
    assert exit_.value.code == 2

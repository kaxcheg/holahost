from pydantic import SecretStr

from application.dto.generate import GenerateResponseCmd, GenerateResponseResult


class TestGenerateResponseCmd:
    def test_both_secrets_masked(self) -> None:
        cmd = GenerateResponseCmd(
            magic_link=SecretStr("ml-tok"),
            byok=SecretStr("sk-key"),
            message="hi",
            ip_hash="a" * 64,
        )
        text = repr(cmd)
        assert "ml-tok" not in text
        assert "sk-key" not in text
        assert cmd.byok.get_secret_value() == "sk-key"


class TestGenerateResponseResult:
    def test_text(self) -> None:
        assert GenerateResponseResult(response_text="r").response_text == "r"

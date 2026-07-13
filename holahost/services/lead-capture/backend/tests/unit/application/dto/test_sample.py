from application.dto.sample import SampleGenerateCmd, SampleGenerateResult


class TestSampleDTOs:
    def test_cmd_holds_fields(self) -> None:
        cmd = SampleGenerateCmd(message="hi", ip_hash="a" * 64)
        assert (cmd.message, cmd.ip_hash) == ("hi", "a" * 64)

    def test_result_holds_text(self) -> None:
        assert SampleGenerateResult(response_text="ok").response_text == "ok"

    def test_cmd_frozen(self) -> None:
        import dataclasses

        import pytest

        cmd = SampleGenerateCmd(message="hi", ip_hash="a" * 64)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.message = "x"  # type: ignore[misc]

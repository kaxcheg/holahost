from domain.entities.generated_reply import GeneratedReply


class TestGeneratedReply:
    def test_create_sets_fields(self) -> None:
        reply = GeneratedReply.create(text="Hello guest!", output_tokens=12)
        assert reply.text == "Hello guest!"
        assert reply.output_tokens == 12

    def test_create_accepts_empty_text(self) -> None:
        reply = GeneratedReply.create(text="", output_tokens=0)
        assert reply.text == ""
        assert reply.output_tokens == 0

    def test_value_equality(self) -> None:
        a = GeneratedReply.create(text="Hi", output_tokens=5)
        b = GeneratedReply.create(text="Hi", output_tokens=5)
        assert a == b

    def test_inequality_on_different_fields(self) -> None:
        a = GeneratedReply.create(text="Hi", output_tokens=5)
        b = GeneratedReply.create(text="Hi", output_tokens=6)
        assert a != b
        c = GeneratedReply.create(text="Bye", output_tokens=5)
        assert a != c

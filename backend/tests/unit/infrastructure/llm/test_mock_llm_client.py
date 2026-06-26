from pydantic import SecretStr

from domain.entities.guest_message import GuestMessage
from infrastructure.llm.mock_llm_client import MockLLMClient
from tests._support.builders import make_chunk, make_guidebook_id


def test_returns_deterministic_reply() -> None:
    reply = MockLLMClient(output_tokens=7).generate(
        chunks=[make_chunk(make_guidebook_id())],
        guest_message=GuestMessage.create("hi"),
        model_id="mock-model",
        system_prompt="sys",
        max_output_tokens=100,
        api_key=SecretStr("x"),
        is_byok=False,
    )
    assert reply.output_tokens == 7
    assert "mock-model" in reply.text and "hi" in reply.text

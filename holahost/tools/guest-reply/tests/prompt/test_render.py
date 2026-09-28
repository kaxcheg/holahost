"""The prompt: the shipped assets, filled by substitution."""

from __future__ import annotations

from pathlib import Path

from guest_reply.clients.documents import Chunk
from guest_reply.prompt import render as render_module
from guest_reply.prompt.render import render


def _chunk(text: str, number: int = 0) -> Chunk:
    return Chunk(chunk_id=f"c{number}", text=text, page=None, score=0.5)


def test_the_system_prompt_is_the_shipped_asset() -> None:
    system, _ = render([_chunk("x")], "hi")
    asset = Path(render_module.__file__).with_name("system.txt")
    assert system == asset.read_text(encoding="utf-8").rstrip("\n")


def test_one_user_message_carries_the_fragments_and_the_guest_message() -> None:
    _, messages = render([_chunk("Check-in 15:00", 0), _chunk("Parking free", 1)], "When?")
    [message] = messages
    assert message.role == "user"
    for text in ("Check-in 15:00", "Parking free", "When?"):
        assert text in message.content


def test_the_fragments_keep_the_search_order_and_are_numbered() -> None:
    _, [message] = render([_chunk("first", 0), _chunk("second", 1)], "q")
    content = message.content
    assert content.index("first") < content.index("second")
    assert content.index('<fragment number="1">') < content.index('<fragment number="2">')


def test_the_guest_message_follows_the_guidebook() -> None:
    _, [message] = render([_chunk("fragment")], "When can I check in?")
    assert message.content.index("</guidebook>") < message.content.index("When can I check in?")


def test_a_dollar_sign_in_the_values_stays_text() -> None:
    _, [message] = render([_chunk("Price $fragments $100")], "Is it $guest_message?")
    assert "Price $fragments $100" in message.content
    assert "Is it $guest_message?" in message.content

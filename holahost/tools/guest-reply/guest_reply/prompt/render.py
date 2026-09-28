"""The "answer the guest" prompt: static assets, filled by substitution.

The assets are the product logic, kept as data: `system.txt` is the host's role and the rules for
answering, `context.tmpl` the user turn, `fragment.tmpl` one retrieved fragment. The code reads them
and substitutes values; it never branches on what a fragment says. `string.Template` substitutes in
one pass, so a `$` inside a fragment or a guest's message stays text.
"""

from __future__ import annotations

from pathlib import Path
from string import Template

from guest_reply.clients.documents import Chunk
from guest_reply.clients.generation import Message

_ASSETS = Path(__file__).parent
_FRAGMENT_SEPARATOR = "\n\n"


def render(chunks: list[Chunk], guest_message: str) -> tuple[str, list[Message]]:
    """The system prompt and the one user turn for `guest_message`, grounded on `chunks`."""
    fragment = Template(_asset("fragment.tmpl"))
    fragments = _FRAGMENT_SEPARATOR.join(
        fragment.substitute(number=number, text=chunk.text)
        for number, chunk in enumerate(chunks, start=1)
    )
    user = Template(_asset("context.tmpl")).substitute(
        fragments=fragments, guest_message=guest_message
    )
    return _asset("system.txt"), [Message(role="user", content=user)]


def _asset(name: str) -> str:
    # The file's final newline is the editor's, not the prompt's.
    return (_ASSETS / name).read_text(encoding="utf-8").rstrip("\n")

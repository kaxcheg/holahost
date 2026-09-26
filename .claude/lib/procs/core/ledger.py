"""The protocol ledger: one checkbox per checkpoint of a rigid procedure, kept in a markdown state file.

Two readers live here on purpose. `legacy_open_lines` reproduces, line for line, what the original bash hook
extracted with `sed` and `grep`, because the text it returns is injected into the model's context verbatim.
`Ledger` is the structured view used wherever a decision is taken (ordering gates, status, the step pointer).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from procs.core import mdsections

LEDGER_TITLE = "Protocol ledger"

_LEDGER_START = re.compile(r"^## Protocol ledger")
_H2 = re.compile(r"^## ")
_OPEN = re.compile(r"^[ \t\n\r\f\v]*- \[ \]")


def has_ledger(text: str) -> bool:
    """`grep -q '^## Protocol ledger'`."""
    return any(_LEDGER_START.match(line) for line in mdsections.lines_of(text))


def legacy_open_lines(text: str) -> list[str]:
    """`sed -n '/^## Protocol ledger/,/^## /{/^## /d;p}' | grep -E '^[[:space:]]*- \\[ \\]'`.

    A range opens at a ledger heading and closes at the next `## ` line; both delimiters are dropped. The line
    that closes a range never opens a new one, exactly as in sed. Matching lines are returned untouched,
    trailing "\\r" included.
    """
    out: list[str] = []
    in_range = False
    lines = mdsections.lines_of(text)
    if lines and lines[-1] == "":
        lines = lines[:-1]  # the split artefact after a final newline is not a line sed would see
    for line in lines:
        if not in_range:
            if _LEDGER_START.match(line):
                in_range = True
            continue
        if _H2.match(line):
            in_range = False
            continue
        if _OPEN.match(line):
            out.append(line)
    return out


@dataclass(frozen=True, slots=True)
class Checkpoint:
    text: str
    done: bool
    line: int

    @property
    def label(self) -> str:
        """The checkpoint's name without its evidence suffix: `context7: design — fastapi` → `context7: design`."""
        return re.split(r"\s+—\s+|\s+-\s+", self.text, maxsplit=1)[0].strip()


@dataclass(frozen=True, slots=True)
class Ledger:
    checkpoints: tuple[Checkpoint, ...]

    @classmethod
    def parse(cls, text: str) -> Ledger | None:
        """None when the file has no ledger section — callers must tell "no ledger" from "all ticked"."""
        section = mdsections.find_section(text, LEDGER_TITLE, max_level=2)
        if section is None or section.heading.level != 2:
            return None
        body = mdsections.section_lines(text, section)
        boxes = mdsections.checkboxes(body, first_line=section.start + 1)
        return cls(tuple(Checkpoint(box.text.strip(), box.checked, box.line) for box in boxes))

    def open(self) -> tuple[Checkpoint, ...]:
        return tuple(c for c in self.checkpoints if not c.done)

    def first_open(self) -> Checkpoint | None:
        pending = self.open()
        return pending[0] if pending else None

    def is_done(self, label_prefix: str) -> bool | None:
        """Whether the checkpoint whose label starts with `label_prefix` is ticked; None when there is none."""
        wanted = label_prefix.casefold()
        for checkpoint in self.checkpoints:
            if checkpoint.label.casefold().startswith(wanted):
                return checkpoint.done
        return None

"""Markdown as structure: headings, the line span each one owns, and task-list checkboxes.

Line numbers are 1-based and refer to the text as split on "\\n" only, so a CRLF file keeps its "\\r" at the
end of each line and the numbers still match what `grep -n` prints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,6}) (.*)$")
_CHECKBOX = re.compile(r"^(\s*)- \[([ xX])\] ?(.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True, slots=True)
class Heading:
    level: int
    title: str
    line: int


@dataclass(frozen=True, slots=True)
class Section:
    """A heading and the lines it owns: up to the next heading of the same or a higher level."""

    heading: Heading
    start: int  # the heading's own line
    end: int  # last owned line, inclusive


@dataclass(frozen=True, slots=True)
class Checkbox:
    checked: bool
    text: str
    line: int
    indent: int


def lines_of(text: str) -> list[str]:
    return text.split("\n")


def headings(text: str, max_level: int = 6, skip_fenced: bool = True) -> list[Heading]:
    """Headings up to `max_level`. Fenced code is skipped by default: a `# comment` in a snippet is no heading."""
    out: list[Heading] = []
    fenced = False
    for number, line in enumerate(lines_of(text), 1):
        if skip_fenced and _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _HEADING.match(line.rstrip("\r"))
        if match and len(match.group(1)) <= max_level:
            out.append(Heading(len(match.group(1)), match.group(2).strip(), number))
    return out


def sections(text: str, max_level: int = 6) -> list[Section]:
    found = headings(text, max_level)
    total = len(lines_of(text))
    out: list[Section] = []
    for i, head in enumerate(found):
        end = total
        for later in found[i + 1 :]:
            if later.level <= head.level:
                end = later.line - 1
                break
        out.append(Section(head, head.line, end))
    return out


def section_lines(text: str, section: Section, with_heading: bool = False) -> list[str]:
    first = section.start if with_heading else section.start + 1
    return lines_of(text)[first - 1 : section.end]


def find_section(text: str, title: str, max_level: int = 6) -> Section | None:
    """The first section whose title equals `title`, ignoring case and surrounding whitespace."""
    wanted = title.strip().casefold()
    for section in sections(text, max_level):
        if section.heading.title.casefold() == wanted:
            return section
    return None


def checkboxes(lines: list[str], first_line: int = 1) -> list[Checkbox]:
    out: list[Checkbox] = []
    for offset, line in enumerate(lines):
        match = _CHECKBOX.match(line.rstrip("\r"))
        if match:
            out.append(Checkbox(match.group(2) != " ", match.group(3), first_line + offset, len(match.group(1))))
    return out

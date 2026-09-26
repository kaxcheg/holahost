"""The project specification as `/build-start` needs it: where it is, which heading is which stage, what to load.

The matching of a stage to a heading is «tolerant of analogous wording» in the procedure, so this module never
decides silently: it ranks candidates by keyword hits and reports a tie as ambiguous for the model to settle.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from procs.build.model import Layer
from procs.core import mdsections

SPEC_NAME = re.compile(r"spec|specification|solution[_-]?design|спек", re.IGNORECASE)
NO_SPEC = "No spec file found under ./docs/ (expected a file with `spec` in the name)."
_US_ID = re.compile(r"\bUS-[\w-]*\d[\w-]*")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


class Stage(IntEnum):
    PROBLEM = 1
    TECH_CONSTRAINTS = 2
    USER_STORIES = 3
    DB_SCHEMA = 4
    CONTRACTS = 5
    CONCEPTUAL_FLOW = 6
    DOMAIN_ENTITIES = 7
    USE_CASES = 8
    DETAILED_FLOW = 9
    ADR = 10
    FRONTEND = 11
    INFRASTRUCTURE = 12
    CI_CD = 13
    BACKLOG = 14


STAGE_TITLES: dict[Stage, str] = {
    Stage.PROBLEM: "Problem Statement + Opportunity + Journey",
    Stage.TECH_CONSTRAINTS: "Tech Constraints",
    Stage.USER_STORIES: "User Stories + Acceptance Criteria",
    Stage.DB_SCHEMA: "DB Schema",
    Stage.CONTRACTS: "Contracts",
    Stage.CONCEPTUAL_FLOW: "Conceptual Sequence Flow",
    Stage.DOMAIN_ENTITIES: "Domain Entities",
    Stage.USE_CASES: "Use Cases",
    Stage.DETAILED_FLOW: "Detailed Sequence Flow",
    Stage.ADR: "ADR",
    Stage.FRONTEND: "Frontend",
    Stage.INFRASTRUCTURE: "Infrastructure",
    Stage.CI_CD: "CI/CD + conventions",
    Stage.BACKLOG: "Backlog",
}

STAGE_KEYWORDS: dict[Stage, tuple[str, ...]] = {
    Stage.PROBLEM: ("problem", "opportunity", "journey", "brief"),
    Stage.TECH_CONSTRAINTS: ("tech", "constraints"),
    Stage.USER_STORIES: ("user", "stories", "acceptance"),
    Stage.DB_SCHEMA: ("db", "schema", "database"),
    Stage.CONTRACTS: ("contracts", "api"),
    Stage.CONCEPTUAL_FLOW: ("conceptual", "sequence"),
    Stage.DOMAIN_ENTITIES: ("domain", "entities"),
    Stage.USE_CASES: ("use", "cases"),
    Stage.DETAILED_FLOW: ("detailed", "sequence", "signatures"),
    Stage.ADR: ("adr", "decision"),
    Stage.FRONTEND: ("frontend", "front"),
    Stage.INFRASTRUCTURE: ("infra", "infrastructure", "environments"),
    Stage.CI_CD: ("ci", "cd", "conventions"),
    Stage.BACKLOG: ("backlog", "tickets"),
}

ALWAYS: tuple[Stage, ...] = (Stage.BACKLOG, Stage.TECH_CONSTRAINTS, Stage.ADR)
PER_LAYER: dict[Layer, tuple[Stage, ...]] = {
    Layer.DOMAIN: (Stage.USER_STORIES, Stage.DOMAIN_ENTITIES, Stage.USE_CASES),
    Layer.APPLICATION: (Stage.USER_STORIES, Stage.USE_CASES, Stage.DOMAIN_ENTITIES, Stage.DETAILED_FLOW),
    Layer.INFRASTRUCTURE: (Stage.USER_STORIES, Stage.DB_SCHEMA, Stage.CONTRACTS, Stage.DETAILED_FLOW),
    Layer.INTERFACE: (Stage.USER_STORIES, Stage.CONTRACTS, Stage.DETAILED_FLOW),
    Layer.FRONTEND: (Stage.USER_STORIES, Stage.FRONTEND, Stage.CONTRACTS, Stage.PROBLEM),
    Layer.INFRA: (Stage.INFRASTRUCTURE, Stage.CI_CD),
    Layer.CI_CD: (Stage.CI_CD, Stage.INFRASTRUCTURE),
}


def required_stages(layer: Layer) -> tuple[Stage, ...]:
    """Backlog, Tech Constraints and ADR always; then the layer's own sections. Conceptual (6) is never loaded."""
    return tuple(dict.fromkeys((*ALWAYS, *PER_LAYER[layer])))


@dataclass(frozen=True, slots=True)
class SpecLocation:
    path: str | None  # relative to the project root
    message: str | None  # the stop text when there is no single answer
    candidates: tuple[str, ...] = ()


def locate(project: Path) -> SpecLocation:
    """`ls docs/ 2>/dev/null | grep -iE 'spec|specification|solution[_-]?design|спек'`: exactly one entry, or a stop."""
    docs = project / "docs"
    try:
        names = sorted(name for name in os.listdir(docs) if not name.startswith(".") and SPEC_NAME.search(name))
    except OSError:
        names = []
    if not names:
        return SpecLocation(None, NO_SPEC)
    if len(names) > 1:
        listing = ", ".join(f"docs/{name}" for name in names)
        return SpecLocation(None, f"Several spec files under ./docs/: {listing}. Ask which spec file to use.", tuple(names))
    return SpecLocation(f"docs/{names[0]}", None)


@dataclass(frozen=True, slots=True)
class Candidate:
    section: mdsections.Section
    score: int


@dataclass(frozen=True, slots=True)
class StageMatch:
    stage: Stage
    best: Candidate | None
    ties: tuple[Candidate, ...]  # other candidates indistinguishable from `best` by score and heading level

    @property
    def ambiguous(self) -> bool:
        return bool(self.ties)


def _words(title: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(title)}


def match_stages(text: str) -> dict[Stage, StageMatch]:
    """Each heading (levels 1–4, fenced code skipped) goes to the stage whose keywords it hits most; a heading that
    hits two stages equally is offered to both. Within a stage: more hits first, then the shallower heading."""
    per_stage: dict[Stage, list[Candidate]] = {stage: [] for stage in Stage}
    sections = mdsections.sections(text, max_level=4)
    # The document title spans the whole file; a keyword in it («# Payments API specification») names no stage.
    top_level = [s for s in sections if s.heading.level == 1]
    title = top_level[0] if len(top_level) == 1 else None
    for section in sections:
        if section is title:
            continue
        words = _words(section.heading.title)
        scores = {stage: sum(1 for k in keys if k in words) for stage, keys in STAGE_KEYWORDS.items()}
        top = max(scores.values())
        if top == 0:
            continue
        for stage, score in scores.items():
            if score == top:
                per_stage[stage].append(Candidate(section, score))
    def rank(found: list[Candidate]) -> list[Candidate]:
        return sorted(found, key=lambda c: (-c.score, c.section.heading.level, c.section.start))

    # A sub-heading of a section that another stage already owns is that section's content, not a rival:
    # `### 8.1 Sequence of upload` under «Detailed Sequence Flow» must not pose as the Conceptual flow.
    owned: list[tuple[Stage, mdsections.Section]] = []
    for stage in sorted(per_stage, key=lambda s: -max((c.score for c in per_stage[s]), default=0)):
        ranked = [
            c
            for c in rank(per_stage[stage])
            if not any(o is not stage and sec.start < c.section.start <= sec.end for o, sec in owned)
        ]
        per_stage[stage] = ranked
        if ranked:
            owned.append((stage, ranked[0].section))

    out: dict[Stage, StageMatch] = {}
    for stage in Stage:
        ranked = per_stage[stage]
        if not ranked:
            out[stage] = StageMatch(stage, None, ())
            continue
        best = ranked[0]
        ties = tuple(
            c for c in ranked[1:] if (c.score, c.section.heading.level) == (best.score, best.section.heading.level)
        )
        out[stage] = StageMatch(stage, best, ties)
    return out


@dataclass(frozen=True, slots=True)
class BacklogHit:
    ticket: str
    line: int
    text: str
    group: str | None  # nearest heading above the line inside the backlog section
    story_ids: tuple[str, ...]


def backlog_hits(text: str, backlog: mdsections.Section, tickets: tuple[str, ...]) -> list[BacklogHit]:
    """Lines of the backlog section that name a ticket, with the group heading they sit under.

    Whether that group IS the requested layer is left to the model: group titles are free wording.
    """
    lines = mdsections.lines_of(text)
    inner = [h for h in mdsections.headings(text, max_level=6) if backlog.start < h.line <= backlog.end]
    hits: list[BacklogHit] = []
    for number in range(backlog.start, backlog.end + 1):
        line = lines[number - 1]
        for ticket in tickets:
            if _names(ticket).search(line):
                group = next((h.title for h in reversed(inner) if h.line <= number), None)
                entry = " ".join([line.strip(), *_continuation(lines, number, backlog.end)])
                hits.append(BacklogHit(ticket, number, entry, group, tuple(dict.fromkeys(_US_ID.findall(entry)))))
    return hits


_NEW_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)]|#{1,6})\s")


def _continuation(lines: list[str], number: int, last: int) -> list[str]:
    """The wrapped rest of a backlog entry: the lines after it up to a blank line, a new item or a heading."""
    out: list[str] = []
    for following in lines[number:last]:
        if not following.strip() or _NEW_ITEM.match(following) or following.lstrip().startswith("|"):
            break
        out.append(following.strip())
    return out


def _names(token: str) -> re.Pattern[str]:
    """`token` as a whole id: `B-0` must not match inside `B-06`, nor `B-06` inside `B-06-B-07`."""
    return re.compile(rf"(?<![\w-]){re.escape(token)}(?![\w-])", re.IGNORECASE)


def split_combined(ticket: str, text: str, backlog: mdsections.Section) -> tuple[str, ...]:
    """The individual ids behind a combined ticket id (`B-06-B-07` → `B-06`, `B-07`).

    Ids contain `-` themselves, so the split is whatever partition the backlog confirms: consecutive pieces that
    each name a backlog entry. No such partition — or the id is an entry as it stands — leaves the id whole.
    """
    body = "\n".join(mdsections.section_lines(text, backlog, with_heading=True))
    pieces = ticket.split("-")

    def known(token: str) -> bool:
        return _names(token).search(body) is not None

    def partition(start: int) -> tuple[str, ...] | None:
        if start == len(pieces):
            return ()
        for end in range(start + 1, len(pieces) + 1):
            head = "-".join(pieces[start:end])
            if known(head):
                rest = partition(end)
                if rest is not None:
                    return (head, *rest)
        return None

    if known(ticket):
        return (ticket,)
    return partition(0) or (ticket,)


BACKEND_LAYERS = frozenset({Layer.DOMAIN, Layer.APPLICATION, Layer.INFRASTRUCTURE, Layer.INTERFACE})
_INFRA_PAIR = frozenset({Layer.INFRASTRUCTURE, Layer.INFRA})


def group_layers(group: str | None) -> frozenset[Layer]:
    """The layers a backlog group heading can stand for — empty when the heading is free wording («Shared
    libraries», «Domain and application»), which is the model's to judge.

    `Backend — Infrastructure` is the backend layer. A bare `Infrastructure` is not settled by its name: specs
    that prefix the backend groups use it for deployment (`infra`), others for the backend layer.
    """
    words = _WORD.findall((group or "").casefold())
    backend = words[:1] == ["backend"]
    layer = Layer.parse("-".join(words[1:] if backend else words))
    if layer is None:
        return frozenset()
    if backend:
        return frozenset({layer}) & BACKEND_LAYERS
    return _INFRA_PAIR if layer in _INFRA_PAIR else frozenset({layer})


@dataclass(frozen=True, slots=True)
class StoryRange:
    story_id: str
    section: mdsections.Section | None  # None: no heading inside the stories section names the id


def story_sections(text: str, stories: mdsections.Section, story_ids: tuple[str, ...]) -> list[StoryRange]:
    """The sub-sections of User Stories whose headings name the given story ids."""
    inner = [s for s in mdsections.sections(text, max_level=6) if stories.start < s.start <= stories.end]
    return [StoryRange(story_id, next((s for s in inner if _names(story_id).search(s.heading.title)), None)) for story_id in story_ids]

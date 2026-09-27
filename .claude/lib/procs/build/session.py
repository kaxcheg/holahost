"""Ticket sessions on disk: where a ticket's state lives, which tickets are in progress, what a session.md says.

A ticket's state sits next to its spec's `docs/`: `holahost/services/<svc>/.build-state/<ticket>/`. `state_roots`
finds every such `.build-state/` of the project, and `in_progress_sessions` is the one owner of the question every
build guard and command asks first: a session counts when ANY line matches
`status:\\*{0,2}[[:space:]]*in_progress`, case-insensitively, with or without the bold marks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from procs.build.model import BUILD_STATE_DIR, SESSION_FILE, Session, Status

STATUS_IN_PROGRESS = re.compile(r"status:\*{0,2}[ \t\r\f\v]*in_progress", re.IGNORECASE)
# The deepest directory a spec's `docs/` hangs from: `holahost/services/<svc>`. `bin/procs-hook` repeats the bound in
# its self-gate, which must not import the library.
STATE_DEPTH = 3
_SKIP_DIRS = frozenset({"node_modules", "__pycache__"})  # and every hidden directory

_FIELD = re.compile(r"^\s*-\s*\*\*(?P<key>[^*:]+):\*\*\s*(?P<value>.*?)\s*$")
_BARE_STATUS = re.compile(r"^\s*status:\s*(?P<value>\S.*?)\s*$", re.IGNORECASE)


def read_text(path: str | Path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def mentions_in_progress(text: str) -> bool:
    return any(STATUS_IN_PROGRESS.search(line) for line in text.split("\n"))


def state_dir(spec_path: str, ticket: str) -> str:
    """Where a ticket's state lives, relative to the project: `.build-state/<ticket>` in the directory that holds the
    spec's nearest `docs/`, or at the project root for a spec outside any `docs/`."""
    parts = Path(spec_path).parts[:-1]
    owner = parts[: len(parts) - 1 - parts[::-1].index("docs")] if "docs" in parts else ()
    return os.path.join(*owner, BUILD_STATE_DIR, ticket)


def state_roots(project: str | Path = ".") -> list[str]:
    """Every `.build-state/` of the project, relative to it: at the root and in directories up to STATE_DEPTH levels
    down, past hidden directories and dependency trees."""
    found: list[str] = []
    level = [""]
    for depth in range(STATE_DEPTH + 1):
        deeper: list[str] = []
        for rel in level:
            if os.path.isdir(os.path.join(project, rel, BUILD_STATE_DIR)):
                found.append(os.path.join(rel, BUILD_STATE_DIR))
            if depth == STATE_DEPTH:
                continue
            try:
                with os.scandir(os.path.join(project, rel)) as entries:
                    deeper.extend(
                        os.path.join(rel, e.name)
                        for e in entries
                        if e.is_dir() and not e.name.startswith(".") and e.name not in _SKIP_DIRS
                    )
            except OSError:
                continue
        level = sorted(deeper)
    return sorted(found)


def all_sessions(project: str | Path = ".") -> list[str]:
    """Paths `<root>/<ticket>/session.md` relative to `project`, over every state root, in byte order within each.
    Hidden ticket directories and anything that is not a file are skipped."""
    found: list[str] = []
    for root in state_roots(project):
        try:
            names = sorted(name for name in os.listdir(os.path.join(project, root)) if not name.startswith("."))
        except OSError:
            continue
        found.extend(
            os.path.join(root, name, SESSION_FILE)
            for name in names
            if os.path.isfile(os.path.join(project, root, name, SESSION_FILE))
        )
    return found


def in_progress_sessions(project: str | Path = ".") -> list[str]:
    """The sessions of `all_sessions` whose session.md is readable and says `in_progress`."""
    found: list[str] = []
    for path in all_sessions(project):
        try:
            text = read_text(os.path.join(project, path))
        except OSError:
            continue
        if mentions_in_progress(text):
            found.append(path)
    return found


def ticket_of(session_path: str) -> str:
    return os.path.basename(os.path.dirname(session_path))


def parse(path: str | Path) -> Session:
    """The structured view of a session.md. Unknown or missing fields stay None."""
    path = Path(path)
    text = read_text(path)
    fields: dict[str, str] = {}
    bare_status: str | None = None
    for line in text.split("\n"):
        line = line.rstrip("\r")
        match = _FIELD.match(line)
        if match:
            fields.setdefault(match.group("key").strip().casefold(), match.group("value"))
            continue
        bare = _BARE_STATUS.match(line)
        if bare and bare_status is None:
            bare_status = bare.group("value")
    status_raw = fields.get("status", bare_status)
    status: Status | None = None
    if status_raw is not None:
        value = status_raw.strip().casefold()
        status = next((s for s in Status if s.value == value), None)
    return Session(
        ticket_id=path.parent.name,
        path=path,
        status=status,
        status_raw=status_raw,
    )

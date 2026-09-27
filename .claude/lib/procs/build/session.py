"""Ticket sessions on disk: which tickets are in progress, and what a session.md says.

`in_progress_sessions` is the one owner of the question every build guard and command asks first. It answers
exactly as the original hooks did with
`grep -liE 'status:\\*{0,2}[[:space:]]*in_progress' .build-state/*/session.md`:
a session counts when ANY line matches, case-insensitively, with or without the bold marks.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from procs.build.model import BUILD_STATE_DIR, SESSION_FILE, Session, Status

STATUS_IN_PROGRESS = re.compile(r"status:\*{0,2}[ \t\r\f\v]*in_progress", re.IGNORECASE)

_FIELD = re.compile(r"^\s*-\s*\*\*(?P<key>[^*:]+):\*\*\s*(?P<value>.*?)\s*$")
_BARE_STATUS = re.compile(r"^\s*status:\s*(?P<value>\S.*?)\s*$", re.IGNORECASE)


def read_text(path: str | Path) -> str:
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def mentions_in_progress(text: str) -> bool:
    return any(STATUS_IN_PROGRESS.search(line) for line in text.split("\n"))


def in_progress_sessions(project: str | Path = ".") -> list[str]:
    """Paths `.build-state/<ticket>/session.md` relative to `project`, in the byte order a C-locale glob yields.

    Like the shell glob it replaces, it skips hidden ticket directories and anything that is not a readable file.
    """
    base = os.path.join(str(project), BUILD_STATE_DIR)
    try:
        names = sorted(name for name in os.listdir(base) if not name.startswith("."))
    except OSError:
        return []
    found: list[str] = []
    for name in names:
        full = os.path.join(base, name, SESSION_FILE)
        if not os.path.isfile(full):
            continue
        try:
            text = read_text(full)
        except OSError:
            continue
        if mentions_in_progress(text):
            found.append(os.path.join(BUILD_STATE_DIR, name, SESSION_FILE))
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

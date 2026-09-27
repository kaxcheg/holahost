"""The project's tickets and which one is in progress (for `/build-commit`), and creation of a ticket's state files
from the skill's templates."""

from __future__ import annotations

import os
from pathlib import Path

from procs.build import session
from procs.build.model import BUILD_STATE_DIR, SESSION_FILE, Status
from procs.core import paths

TEMPLATE_TOKEN = "TICKET-ID"
SESSION_TEMPLATE = "session.template.md"
CLARIFICATIONS_TEMPLATE = "clarifications.template.md"


def _status(path: Path) -> str:
    # One definition of «in progress» for the guards, /build-session and this view: the guards' status regex.
    if session.mentions_in_progress(session.read_text(path)):
        return Status.IN_PROGRESS.value
    parsed = session.parse(path)
    return parsed.status.value if parsed.status else f"UNRECOGNISED ({parsed.status_raw!r})"


def render(project: Path, ticket: str | None) -> str:
    """Every ticket of every `.build-state/`, or the one named, with its status and state directory."""
    paths = [p for p in session.all_sessions(project) if ticket is None or session.ticket_of(p) == ticket]
    if not paths:
        return f"TICKET {ticket}: NOT FOUND (no .build-state/{ticket}/session.md)\n" if ticket else "NO TICKETS: no .build-state/ has a session.md\n"
    out: list[str] = []
    active: list[str] = []
    for path in paths:
        name = session.ticket_of(path)
        status = _status(project / path)
        out.append(f"TICKET {name}: status={status} ({os.path.dirname(path)})")
        if status == Status.IN_PROGRESS.value:
            active.append(name)
    if not ticket:
        out.append(f"ACTIVE: {', '.join(active) or 'none'}")
    return "\n".join(out) + "\n"


# --- scaffolding ------------------------------------------------------------------------------


def template_dir(project: Path) -> Path | None:
    """The build-session skill's own directory, where the state templates live."""
    candidate = paths.skill_dir("build-session")
    return candidate if (candidate / SESSION_TEMPLATE).is_file() else None


def scaffold(project: Path, state: str) -> list[str]:
    """Create session.md and clarifications.md in `state` — the `STATE` the route printed, `<…>/.build-state/<ticket>` —
    from the templates with `TICKET-ID` substituted.

    Existing files are never overwritten. Status is `in_progress` from creation, as the protocol requires.
    """
    templates = template_dir(project)
    if templates is None:
        raise FileNotFoundError("session templates not found next to the skill: " + str(paths.skill_dir("build-session")))
    target = project / state
    if target.parent.name != BUILD_STATE_DIR:
        raise ValueError(f"{state} is not a ticket directory under a {BUILD_STATE_DIR}/: pass the route's STATE")
    ticket = target.name
    target.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for template, name in ((SESSION_TEMPLATE, SESSION_FILE), (CLARIFICATIONS_TEMPLATE, "clarifications.md")):
        destination = target / name
        if destination.exists():
            continue
        text = session.read_text(templates / template).replace(TEMPLATE_TOKEN, ticket)
        if name == SESSION_FILE:
            text = text.replace("- **Status:** in_progress | completed", "- **Status:** in_progress")
        destination.write_text(text, encoding="utf-8")
        created.append(str(destination.relative_to(project)))
    return created

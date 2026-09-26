"""Facts for `/build-status`, and creation of a ticket's state files from the skill's templates.

`/build-status` promises numbers — the step reached, entries in clarifications.md, uncommitted files — that were
never stored anywhere. They are counted here from the files; how they are worded stays with the command text.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from procs.build import session
from procs.build.model import BUILD_STATE_DIR, SESSION_FILE, Session, Status
from procs.core import ledger, mdsections, paths

TEMPLATE_TOKEN = "TICKET-ID"
SESSION_TEMPLATE = "session.template.md"
CLARIFICATIONS_TEMPLATE = "clarifications.template.md"


PROGRESS_CHARS = 300


@dataclass(frozen=True, slots=True)
class TicketFacts:
    session: Session
    in_progress: bool
    plan_done: int | None  # ticked checkboxes of plan.md; None when there is no plan
    plan_total: int | None
    progress: str | None  # the `## Progress` section of session.md, flattened
    clarifications: bool  # the file exists
    uncommitted: int | None
    ledger_open: int | None

    @property
    def status(self) -> str:
        if self.in_progress:
            return Status.IN_PROGRESS.value
        return self.session.status.value if self.session.status else f"UNRECOGNISED ({self.session.status_raw!r})"

    @property
    def step(self) -> str:
        """`step 3/5` is the step being worked on — the one after the last ticked — as the command's example shows."""
        if self.plan_total is None or self.plan_done is None:
            return "no plan.md"
        if self.plan_done >= self.plan_total:
            return f"all {self.plan_total} steps ticked"
        return f"step {self.plan_done + 1}/{self.plan_total} ({self.plan_done} ticked)"


def _count_boxes(path: Path) -> tuple[int, int] | None:
    if not path.is_file():
        return None
    boxes = mdsections.checkboxes(mdsections.lines_of(session.read_text(path)))
    return sum(1 for b in boxes if b.checked), len(boxes)


def _section_bullets(text: str, title: str) -> int | None:
    section = mdsections.find_section(text, title)
    if section is None:
        return None
    body = mdsections.section_lines(text, section)
    return sum(1 for line in body if line.lstrip().startswith(("- ", "* ")) and "path/to/file" not in line)


def facts(project: Path, ticket: str) -> TicketFacts | None:
    path = project / BUILD_STATE_DIR / ticket / SESSION_FILE
    if not path.is_file():
        return None
    parsed = session.parse(path)
    text = session.read_text(path)
    plan = _count_boxes(path.parent / "plan.md")
    progress = mdsections.find_section(text, "Progress")
    return TicketFacts(
        session=parsed,
        # One definition of «in progress» for the guards, /build-start and this view: the guards' status regex.
        in_progress=session.mentions_in_progress(text),
        plan_done=plan[0] if plan else None,
        plan_total=plan[1] if plan else None,
        progress=" ".join(line.strip() for line in mdsections.section_lines(text, progress) if line.strip())[:PROGRESS_CHARS] if progress else None,
        # The entry format of clarifications.md is free, so entries are not counted here: the model reads the file.
        clarifications=(path.parent / "clarifications.md").is_file(),
        uncommitted=_section_bullets(text, "Uncommitted Changes"),
        ledger_open=len(parsed.ledger.open()) if parsed.ledger is not None else None,
    )


MAX_PLAN_STEPS = 80


def _plan_steps(plan: Path) -> list[str]:
    """The plan's checkboxes in order — the Done / Current / Remaining material of the single-ticket view."""
    if not plan.is_file():
        return []
    boxes = mdsections.checkboxes(mdsections.lines_of(session.read_text(plan)))
    lines = [f"  [{'x' if b.checked else ' '}] {b.text.replace('**', '').strip()}" for b in boxes[:MAX_PLAN_STEPS]]
    if len(boxes) > MAX_PLAN_STEPS:
        lines.append(f"  … {len(boxes) - MAX_PLAN_STEPS} more in {plan.name}")
    return ["PLAN STEPS:", *lines]


def tickets(project: Path) -> list[str]:
    base = project / BUILD_STATE_DIR
    try:
        return sorted(n for n in os.listdir(base) if not n.startswith(".") and (base / n / SESSION_FILE).is_file())
    except OSError:
        return []


def render(project: Path, ticket: str | None) -> str:
    names = [ticket] if ticket else tickets(project)
    if not names:
        return "NO TICKETS: .build-state/ has no session.md\n"
    out: list[str] = []
    for name in names:
        found = facts(project, name)
        if found is None:
            out.append(f"TICKET {name}: NOT FOUND (.build-state/{name}/session.md is absent)")
            continue
        s = found.session
        out.append(f"TICKET {name}: status={found.status}; branch={s.branch or '—'}; session#={s.session_no or '—'}; layer={s.layer.value if s.layer else '—'}")
        out.append(f"  description: {s.description or '—'}")
        out.append(f"  plan: {found.step}")
        out.append(f"  progress (session.md): {found.progress or '—'}")
        out.append(f"  ledger: {'no ledger section' if found.ledger_open is None else f'{found.ledger_open} open checkpoints'}")
        out.append(f"  uncommitted: {'no section' if found.uncommitted is None else f'{found.uncommitted} files'}")
        if ticket:
            clar = f"{BUILD_STATE_DIR}/{name}/clarifications.md — count its entries by reading it" if found.clarifications else "no file"
            out.append(f"  clarifications: {clar}")
            out.extend(_plan_steps(project / BUILD_STATE_DIR / name / "plan.md"))
    active = [n for n in names if (f := facts(project, n)) is not None and f.in_progress]
    if not ticket:
        out.append(f"ACTIVE: {', '.join(active) or 'none'}")
    return "\n".join(out) + "\n"


# --- scaffolding ------------------------------------------------------------------------------


def template_dir(project: Path) -> Path | None:
    """The build-session skill's own directory, where the state templates live."""
    candidate = paths.skill_dir("build-session")
    return candidate if (candidate / SESSION_TEMPLATE).is_file() else None


def scaffold(project: Path, ticket: str, layer: str | None = None) -> list[str]:
    """Create session.md and clarifications.md from the templates with `TICKET-ID` substituted.

    Existing files are never overwritten. Status is `in_progress` from creation, as the protocol requires.
    """
    templates = template_dir(project)
    if templates is None:
        raise FileNotFoundError("session templates not found next to the skill: " + str(paths.skill_dir("build-session")))
    target = project / BUILD_STATE_DIR / ticket
    target.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for template, name in ((SESSION_TEMPLATE, SESSION_FILE), (CLARIFICATIONS_TEMPLATE, "clarifications.md")):
        destination = target / name
        if destination.exists():
            continue
        text = session.read_text(templates / template).replace(TEMPLATE_TOKEN, ticket)
        if name == SESSION_FILE:
            text = text.replace("- **Status:** in_progress | completed", "- **Status:** in_progress")
            if layer:
                text = text.replace("- **Layer:** <layer>", f"- **Layer:** {layer}")
        destination.write_text(text, encoding="utf-8")
        created.append(str(destination.relative_to(project)))
    return created


def migrate_session(project: Path, ticket: str) -> bool:
    """Insert the Protocol ledger of the current template into a session.md that predates it. Idempotent."""
    path = project / BUILD_STATE_DIR / ticket / SESSION_FILE
    text = session.read_text(path)
    templates = template_dir(project)
    if ledger.has_ledger(text) or templates is None:
        return False
    template = session.read_text(templates / SESSION_TEMPLATE)
    section = mdsections.find_section(template, ledger.LEDGER_TITLE, max_level=2)
    if section is None:
        return False
    block = "\n".join(mdsections.section_lines(template, section, with_heading=True)).rstrip("\n") + "\n\n"
    anchor = mdsections.find_section(text, "Progress", max_level=2)
    lines = mdsections.lines_of(text)
    if anchor is None:
        new = text.rstrip("\n") + "\n\n" + block.rstrip("\n") + "\n"
    else:
        new = "\n".join(lines[: anchor.start - 1]) + "\n" + block + "\n".join(lines[anchor.start - 1 :])
    path.write_text(new, encoding="utf-8")
    return True

"""Guards of the build family: the mechanical half of the build-session checkpoints.

Each guard takes the raw hook stdin and returns (stdout, stderr, exit code). Their observable behaviour —
messages, exit codes, the evidence file, the order tickets are reported in — used to be pinned by golden tests
against the bash hooks they replace; that apparatus was removed, so the behaviour is now held by this code alone.

All of them are silent unless the project has a ticket whose session.md says `in_progress`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import traceback
from collections.abc import Callable
from typing import Any

from procs.build import session
from procs.build.model import CONTEXT7_LOG, CONTEXT_WATCH, Context7Lookup
from procs.core import ledger, paths

Result = tuple[str, str, int]
Guard = Callable[[str], Result]
SILENT: Result = ("", "", 0)

_MODELS_ROW = re.compile(r"^\|\s*`(low_model|high_model)`\s*\|\s*`([^`]+)`", re.M)
FALLBACK_MODELS = {"sonnet": "low_model", "fable": "high_model"}
GATED_TICKET_FILES = ("plan.md",)


def _enter_project() -> list[str] | None:
    """chdir to the session's project root and list its in_progress sessions; None means «stay silent».

    The guards work with paths relative to the project root, exactly as the hooks did after their `cd`.
    """
    try:
        os.chdir(os.environ.get("CLAUDE_PROJECT_DIR") or ".")
        return session.in_progress_sessions(".") or None
    except Exception:
        return None  # before a ticket is established every failure is open: no ticket, no guard


def _closed(name: str, guard: Guard) -> Guard:
    """Fail closed once a ticket is in progress (D-01).

    `_enter_project` swallows its own failures, so an exception that reaches this wrapper was raised after the
    self-gate found an in_progress ticket. Letting the call through then would skip a checkpoint silently, which
    is what these two guards exist to prevent.
    """

    def wrapped(stdin: str) -> Result:
        try:
            return guard(stdin)
        except Exception as exc:
            return (
                "",
                f"build-session ⏹ {name}: the guard itself failed ({type(exc).__name__}: {exc}) while a ticket is "
                "in_progress, so the call is blocked rather than let through unchecked. This is not a checkpoint you "
                "skipped: report it to the user and wait — do not work around it. (Only the user switches guards "
                "off: `touch ~/.claude/procs.guards.off` or `PROCS_GUARDS=off`.)\n",
                2,
            )

    return wrapped


def _payload(stdin: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(stdin)
    return data


def _tool_input(stdin: str) -> dict[str, Any]:
    tool_input: dict[str, Any] = _payload(stdin).get("tool_input") or {}
    return tool_input


def ledger_context(stdin: str) -> Result:
    """UserPromptSubmit: put the open checkpoints of every in_progress ticket into context."""
    sessions = _enter_project()
    if sessions is None:
        return SILENT
    out: list[str] = []
    for path in sessions:
        ticket = session.ticket_of(path)
        text = session.read_text(path)
        if not ledger.has_ledger(text):
            out.append(
                f"build-session ⏹ {ticket}: {path} has no '## Protocol ledger' section — add it from "
                "session.template.md (.claude/skills/build-session/) before continuing."
            )
            continue
        pending = ledger.legacy_open_lines(text)
        if pending:
            out.append(
                f"build-session ⏹ {ticket} — open checkpoints (tick in {path} with evidence; an open checkpoint "
                "blocks the step after it):"
            )
            out.extend(pending)
    return ("\n".join(out) + "\n" if out else "", "", 0)


DESIGN_APPROVED, PLAN_APPROVED = "design approved", "plan approved"


def allowed_models() -> dict[str, str]:
    """value → setting name, read from the `## Models` table of the build-session SKILL.md.

    The table lives in the project's `.claude/skills/build-session/SKILL.md`, so that skill stays the single owner of
    the mapping. A file without the table falls back to the built-in pair.
    """
    candidates = [str(paths.skill_dir("build-session") / "SKILL.md")]
    allowed: dict[str, str] = {}
    for path in candidates:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for match in _MODELS_ROW.finditer(fh.read()):
                    allowed[match.group(2)] = match.group(1)
            break
    return allowed or dict(FALLBACK_MODELS)


def agent_model(stdin: str) -> Result:
    """PreToolUse Agent|Task: a dispatch must carry an explicit, allowed `model` while a ticket is in progress."""
    if _enter_project() is None:
        return SILENT
    payload = _payload(stdin)
    if payload.get("agent_id"):
        # The Models rule addresses the main loop. A dispatch made from inside a subagent — the code-review run
        # spawns its own — comes from a context that never read the skill and cannot know the settings.
        return SILENT
    tool_input: dict[str, Any] = payload.get("tool_input") or {}
    if tool_input.get("subagent_type") == "fork":
        return SILENT  # a fork always runs on the parent model; the parameter is ignored
    allowed = allowed_models()
    model = tool_input.get("model")
    if model in allowed:
        return SILENT
    listing = ", ".join(f"{name}={value}" for value, name in allowed.items())
    return (
        "",
        "build-session ## Models: Agent dispatch blocked — pass the model explicitly, never inherit the main-loop "
        f"model. Allowed: {listing}. Got model={model!r} (subagent_type={tool_input.get('subagent_type')!r}).\n",
        2,
    )


def _logged(ticket_dir: str) -> bool:
    path = os.path.join(ticket_dir, CONTEXT7_LOG)
    return os.path.exists(path) and os.path.getsize(path) > 0


def context7_gate(stdin: str) -> Result:
    """PreToolUse Write|Edit|NotebookEdit: no plan or project file before a recorded Context7 lookup.

    session.md, clarifications.md, anything under .claude/ and anything outside the project are never gated.
    """
    sessions = _enter_project()
    if sessions is None:
        return SILENT
    tool_input = _tool_input(stdin)
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    root = os.getcwd()
    absolute = os.path.abspath(path) if path else ""
    if not absolute.startswith(root + os.sep):
        return SILENT
    rel = os.path.relpath(absolute, root)
    parts = rel.split(os.sep)
    if parts[0] == ".claude":
        return SILENT
    tickets = {session.ticket_of(s): os.path.dirname(s) for s in sessions}
    if parts[0] == ".build-state":
        if len(parts) < 3 or parts[2] not in GATED_TICKET_FILES or parts[1] not in tickets:
            return SILENT
        need = {parts[1]: tickets[parts[1]]}
    else:
        need = tickets  # a project file: a lookup recorded for any in_progress ticket suffices
    if any(_logged(directory) for directory in need.values()):
        return SILENT
    logs = ", ".join(os.path.join(directory, CONTEXT7_LOG) for directory in need.values())
    return (
        "",
        f"build-session ⏹ Context7 checkpoint not met for {', '.join(need)}: nothing recorded in {logs}. Run "
        "resolve-library-id → query-docs for every library this work touches (build-session ## Context7), tick the "
        f"ledger line in session.md, then retry writing {rel}.\n",
        2,
    )


def _project_relative(tool_input: dict[str, Any]) -> list[str] | None:
    """Path parts of the written file relative to the project root; None when the guards have no say over it
    (no path, outside the project, or under `.claude/`)."""
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    root = os.getcwd()
    absolute = os.path.abspath(path) if path else ""
    if not absolute.startswith(root + os.sep):
        return None
    parts = os.path.relpath(absolute, root).split(os.sep)
    return None if parts[0] == ".claude" else parts


def ledger_gate(stdin: str) -> Result:
    """PreToolUse Write|Edit|NotebookEdit: «an unticked checkpoint blocks the step after it», for the two approvals.

    plan.md needs «design approved»; project files need «plan approved». A session without a ledger
    section, or a ledger without the line, is never blocked: the guard enforces a checkpoint, it does not invent one.
    For a project file it is enough that one in_progress ticket has its plan approved — the file cannot be
    attributed to a ticket mechanically.
    """
    sessions = _enter_project()
    if sessions is None:
        return SILENT
    parts = _project_relative(_tool_input(stdin))
    if parts is None:
        return SILENT
    ledgers = {session.ticket_of(s): ledger.Ledger.parse(session.read_text(s)) for s in sessions}
    rel = os.sep.join(parts)
    if parts[0] == ".build-state":
        if len(parts) < 3 or parts[2] not in GATED_TICKET_FILES or parts[1] not in ledgers:
            return SILENT
        needed = DESIGN_APPROVED
        parsed = ledgers[parts[1]]
        if parsed is None or parsed.is_done(needed) is not False:
            return SILENT
        blocked = [parts[1]]
    else:
        needed = PLAN_APPROVED
        states = [parsed.is_done(needed) for parsed in ledgers.values() if parsed is not None]
        if not states or any(state is not False for state in states):
            return SILENT
        blocked = [ticket for ticket, parsed in ledgers.items() if parsed is not None]
    return (
        "",
        f"build-session ⏹ {', '.join(blocked)}: «{needed}» is not ticked in the Protocol ledger, and {rel} belongs to "
        "the step after it. Get the user's approval, tick the ledger line in session.md with the evidence, then "
        "retry.\n",
        2,
    )


DEFAULT_BRANCHES = ("main", "master", "develop")
_GIT_COMMIT = re.compile(r"(?:^|[;&|(]\s*)git(?P<options>(?:\s+-[Cc]\s+\S+)*)\s+commit\b")
_CD = re.compile(r"(?:^|[;&|(]\s*)cd\s+(\S+)")
_DASH_C = re.compile(r"\s-C\s+(\S+)")


def commit_dir(command: str, cwd: str) -> str | None:
    """The directory the first `git commit` of a shell command runs in, as far as its text tells: every `cd` before
    it, then its own `-C` options. None when there is no `git commit`, or a path holds something only the shell can
    resolve (`$VAR`, a substitution) — a commit that cannot be attributed is not the guard's business."""
    found = _GIT_COMMIT.search(command)
    if found is None:
        return None
    steps = [m.group(1) for m in _CD.finditer(command, 0, found.start() + 1)]
    steps += [m.group(1) for m in _DASH_C.finditer(found.group("options"))]
    where = cwd
    for step in steps:
        step = os.path.expanduser(step.strip("\"'"))
        if "$" in step or "`" in step:
            return None
        where = os.path.join(where, step)
    return os.path.realpath(where)


def current_branch(start: str = ".", top: str | None = None) -> str | None:
    """The branch checked out at `start`: `HEAD` of the nearest `.git` at or above it, not looking above `top`
    (a worktree's `.git` file is followed). None when detached or when there is no repository."""
    here, top = os.path.abspath(start), os.path.abspath(top or start)
    while not os.path.exists(os.path.join(here, ".git")):
        if here == top or os.path.dirname(here) == here:
            return None
        here = os.path.dirname(here)
    git = os.path.join(here, ".git")
    try:
        if os.path.isfile(git):
            with open(git, encoding="utf-8") as fh:
                pointer = fh.read().strip()
            if pointer.startswith("gitdir:"):
                git = os.path.join(here, pointer.partition(":")[2].strip())
        with open(os.path.join(git, "HEAD"), encoding="utf-8") as fh:
            head = fh.read().strip()
    except OSError:
        return None
    return head.removeprefix("ref: refs/heads/") if head.startswith("ref: refs/heads/") else None


def branch_gate(stdin: str) -> Result:
    """PreToolUse Bash: no `git commit` on the default branch while a ticket is in progress.

    /build-commit «applies to feature branches only»; Setup creates the ticket branch before any code exists.
    Only a commit that lands inside the session's project is judged: `git -C <elsewhere> commit`, a `cd` out of
    the project, or a shell cwd outside it belong to another repository.
    """
    sessions = _enter_project()
    if sessions is None:
        return SILENT
    payload = _payload(stdin)
    command = (payload.get("tool_input") or {}).get("command") or ""
    root = os.getcwd()
    cwd = payload.get("cwd")
    where = commit_dir(command, cwd if isinstance(cwd, str) and cwd else root) if isinstance(command, str) else None
    if where is None or not (where == root or where.startswith(root + os.sep)):
        return SILENT
    branch = current_branch(where, root)
    if branch not in DEFAULT_BRANCHES:
        return SILENT
    tickets = ", ".join(session.ticket_of(s) for s in sessions)
    return (
        "",
        f"build-session ⏹ {tickets}: `git commit` on the default branch `{branch}` while a ticket is in_progress. "
        "Ticket work is committed on its feature branch (build-session Setup, step 5; /build-commit applies to "
        "feature branches only). Switch to the ticket branch, or commit outside the session if this is unrelated.\n",
        2,
    )


def context7_mark(stdin: str) -> Result:
    """PostToolUse query-docs: record the lookup in context7.log of every in_progress ticket."""
    sessions = _enter_project()
    if sessions is None:
        return SILENT
    errors: list[str] = []
    for path in sessions:
        try:
            tool_input = _tool_input(stdin)
            lookup = Context7Lookup(dt.datetime.now(), tool_input.get("libraryId", "?"), tool_input.get("query") or "")
            with open(os.path.join(os.path.dirname(path), CONTEXT7_LOG), "a", encoding="utf-8") as fh:
                fh.write(lookup.log_line())
        except Exception:
            errors.append(traceback.format_exc())
    # A lookup that could not be recorded is reported (exit 1 is a visible, non-blocking hook error): the gate
    # would otherwise keep blocking writes with no hint that the evidence was never written (D-01).
    return ("", "".join(errors), 1 if errors else 0)


DEFAULT_COMPACT_AT = 835_000  # where sessions here compacted while `autoCompactWindow` was not set
REMIND_AT = 150_000  # tokens left before auto-compaction


def context_used(transcript: str) -> int:
    """Input tokens of the session's last API response: what its context holds, counted as the status line does."""
    with open(transcript, "rb") as fh:
        fh.seek(max(0, fh.seek(0, os.SEEK_END) - 4_000_000))
        lines = fh.read().split(b"\n")
    for raw in reversed(lines):
        if b'"assistant"' not in raw or b'"usage"' not in raw:
            continue
        try:
            entry = json.loads(raw)
        except ValueError:
            continue  # the first line of the tail is cut
        usage = (entry.get("message") or {}).get("usage") or {}
        used = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        if entry.get("type") == "assistant" and not entry.get("isSidechain") and used:
            return used  # a synthetic message (an API error) carries zero usage
    return 0


def context_watch(stdin: str) -> Result:
    """UserPromptSubmit + PostToolUse: once per session, and again after a compaction, tell the model and the user
    that auto-compaction is REMIND_AT tokens away — the ticket is not restored after it. Fails open."""
    sessions = _enter_project()
    if sessions is None:
        return SILENT
    try:
        payload = _payload(stdin)
        if payload.get("agent_id"):
            return SILENT  # a subagent's context is not the session's
        try:
            config = os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")
            with open(os.path.join(config, "settings.json"), encoding="utf-8") as fh:
                at = json.load(fh).get("autoCompactWindow") or DEFAULT_COMPACT_AT
        except OSError:
            at = DEFAULT_COMPACT_AT
        used = context_used(payload["transcript_path"])
        marker = os.path.join(os.path.dirname(sessions[0]), CONTEXT_WATCH)
        told = os.path.isfile(marker) and session.read_text(marker) == payload["session_id"]
        if used < at - REMIND_AT:
            if told:
                os.remove(marker)  # the context shrank — a compaction: the reminder is due again
            return SILENT
        if told:
            return SILENT
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(payload["session_id"])
        fill = f"{used // 1000}k of {at // 1000}k"
        model_text = (
            f"build-session: context {fill} — auto-compaction is near and the ticket is not restored after it. "
            "Tell the user and, at the next safe point, offer to save the state by hand."
        )
        user_text = f"build: context {fill} — auto-compaction is near; save the state by hand if needed."
        output = {
            "hookSpecificOutput": {"hookEventName": payload["hook_event_name"], "additionalContext": model_text},
            "systemMessage": user_text,
        }
        return (json.dumps(output) + "\n", "", 0)
    except Exception:
        return SILENT


GUARDS: dict[str, Guard] = {
    "ledger-context": ledger_context,
    "agent-model": _closed("agent-model", agent_model),
    "context7-gate": _closed("context7-gate", context7_gate),
    "context7-mark": context7_mark,
    "context-watch": context_watch,
    "ledger-gate": ledger_gate,
    "branch-gate": branch_gate,
}

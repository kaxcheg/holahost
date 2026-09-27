"""`procs build …` — the deterministic sub-procedures of /build-session and /build-commit.

`route` and `status` are read-only and meant for a skill's `!` injection: they exit 0 for every domain outcome
and carry «stop» in their output. `scaffold` writes and is therefore run by the model.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from procs.build import route, status
from procs.core import paths


def _project(args: argparse.Namespace) -> Path:
    return Path(args.project) if args.project else paths.project_dir()


def _cmd_route(args: argparse.Namespace) -> int:
    project = _project(args)
    # Arguments arrive on stdin through a quoted heredoc, so no shell ever interprets them.
    line = " ".join(args.args) if args.args else sys.stdin.read()
    decided = route.decide(project, line.replace("\n", " "))
    sys.stdout.write(route.render(project, decided))
    if args.headings and decided.spec:
        sys.stdout.write("HEADINGS:\n" + route.headings_listing(project, decided.spec))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    line = " ".join(args.args) if args.args else ("" if sys.stdin.isatty() else sys.stdin.read())
    tokens = line.split()
    sys.stdout.write(status.render(_project(args), tokens[0] if tokens else None))
    return 0


def _cmd_scaffold(args: argparse.Namespace) -> int:
    try:
        created = status.scaffold(_project(args), args.state)
    except (FileNotFoundError, ValueError) as exc:
        print(f"procs build scaffold: {exc}", file=sys.stderr)
        return 1
    for path in created:
        print(f"created {path}")
    if not created:
        print(f"nothing created: {args.state}/ already has its state files")
    return 0


def register(sub: Any) -> None:
    build = sub.add_parser("build", help="ticket routing, status and state files of the build family")
    commands = build.add_subparsers(dest="command", required=True)

    p = commands.add_parser("route", help="start/stop/ask decision, spec location and the sections to load")
    p.add_argument("--project")
    p.add_argument("--headings", action="store_true", help="append the spec's heading index")
    p.add_argument("args", nargs="*", help="the /build-session arguments (default: read them from stdin)")
    p.set_defaults(func=_cmd_route)

    p = commands.add_parser("status", help="the tickets and which one is in progress, for /build-commit")
    p.add_argument("--project")
    p.add_argument("args", nargs="*", help="optional ticket id (default: read it from stdin)")
    p.set_defaults(func=_cmd_status)

    p = commands.add_parser("scaffold", help="create session.md and clarifications.md from the skill's templates")
    p.add_argument("--project")
    p.add_argument("state", help="the ticket's state directory, as the route's STATE line prints it")
    p.set_defaults(func=_cmd_scaffold)

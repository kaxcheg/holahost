"""`procs build <command>` — the deterministic sub-procedures of the build protocol.

The executable sits in the project's `.claude/bin/`; the skills call it as `python3 .claude/bin/procs build …` from the
project root, the one spelling the project's permission rule names.

A command meant for a skill's `!` injection exits 0 for every domain outcome, "stop" included, and keeps non-zero for
internal errors only: a failing injected command makes the skill vanish without a word (measured: S1b/S1c).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from procs.build import cli as build_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="procs", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="domain", required=True)
    build_cli.register(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.func(args)
    return result

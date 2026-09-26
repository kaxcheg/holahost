"""Registry of guards behind `bin/procs-hook <guard>`.

A guard is a function of the raw stdin text returning (stdout, stderr, exit code). Raw text, not a parsed
HookInput, because the legacy hooks differ in how they read stdin — one never parses it — and their observable
behaviour on malformed input is part of what the golden tests pin.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable

Guard = Callable[[str], tuple[str, str, int]]

# Modules that export `GUARDS: dict[str, Guard]`. A domain that is not installed is simply absent.
GUARD_MODULES = ("procs.build.guards",)


def registry() -> dict[str, Guard]:
    guards: dict[str, Guard] = {}
    for name in GUARD_MODULES:
        try:
            module = importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        guards.update(module.GUARDS)
    return guards


def run(name: str) -> int:
    guard = registry().get(name)
    if guard is None:
        # An unknown name is a wiring mistake, never a reason to block the user's tool call.
        sys.stderr.write(f"procs-hook: unknown guard {name!r}\n")
        return 0
    # Bytes in, bytes out: the text carries non-ASCII marks and must not depend on the process locale.
    stdout, stderr, code = guard(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    sys.stdout.buffer.write(stdout.encode("utf-8"))
    sys.stderr.buffer.write(stderr.encode("utf-8"))
    return code

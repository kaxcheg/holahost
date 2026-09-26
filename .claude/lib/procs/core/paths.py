"""Where the procedure's own files and the session's project live.

The kill switch is not here: `bin/procs-hook` checks it inline, in its first statement, before importing anything —
so a broken library cannot take away the way to switch the library off. Everything that only served that check
(`config_dir`, `guards_disabled`, `GUARDS_OFF_FILE`) is gone.
"""

from __future__ import annotations

import os
from pathlib import Path


def install_root() -> Path:
    """The project's `.claude` directory this copy of the library lives in.

    `lib/procs/core/paths.py` → three levels up is `lib/`, four is `.claude`. Derived from `__file__` and not from an
    environment variable, so a plain `python3 .claude/bin/procs …` run from a shell resolves the same path.
    """
    return Path(__file__).resolve().parents[3]


def skill_dir(skill: str) -> Path:
    """The directory of the project skill `skill`: `.claude/skills/<skill>`."""
    return install_root() / "skills" / skill


def project_dir() -> Path:
    """The session's project root: `$CLAUDE_PROJECT_DIR`, else the current directory.

    The harness keeps the variable at the session root while the model's cwd moves, which is why state that lives
    at the project root (`.build-state/`) is anchored on it and not on `cwd`.
    """
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".")

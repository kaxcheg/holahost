"""Entities of the build family, as the procedures and their state files define them."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path

from procs.core.ledger import Ledger

BUILD_STATE_DIR = ".build-state"
SESSION_FILE = "session.md"
CONTEXT7_LOG = "context7.log"
TICKET_FILES = ("session.md", "clarifications.md", "plan.md", "design.md")


class Status(StrEnum):
    IN_PROGRESS = auto()
    COMPLETED = auto()


class Layer(StrEnum):
    DOMAIN = auto()
    APPLICATION = auto()
    INFRASTRUCTURE = auto()
    INTERFACE = auto()
    FRONTEND = auto()
    INFRA = auto()
    CI_CD = "ci-cd"

    @classmethod
    def parse(cls, token: str) -> Layer | None:
        try:
            return cls(token.strip().lower())
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class Session:
    """`.build-state/<ticket>/session.md`. Fields the file does not carry are None, never guessed."""

    ticket_id: str
    path: Path
    status: Status | None
    status_raw: str | None
    layer: Layer | None
    branch: str | None
    session_no: int | None
    description: str | None
    ledger: Ledger | None

    @property
    def directory(self) -> Path:
        return self.path.parent


@dataclass(frozen=True, slots=True)
class ModelSetting:
    """One row of the `## Models` table of the build-session skill, the single owner of the mapping."""

    name: str  # low_model | high_model
    value: str  # the `model` parameter an Agent dispatch must carry


@dataclass(frozen=True, slots=True)
class Context7Lookup:
    at: dt.datetime
    library_id: str
    query: str

    def log_line(self) -> str:
        """The evidence line of context7.log; the query is flattened to one line and cut at 120 characters."""
        flat = self.query.replace("\n", " ")[:120]
        return f"{self.at:%Y-%m-%d %H:%M} {self.library_id} — {flat}\n"

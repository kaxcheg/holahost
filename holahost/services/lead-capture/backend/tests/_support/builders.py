"""Shared test builders for valid domain objects (reused across application/infra tests)."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from pydantic import SecretStr

from domain.entities.chunk import Chunk
from domain.entities.guidebook import Guidebook
from domain.entities.lead import Lead
from domain.value_objects.email import Email
from domain.value_objects.embedding import EMBEDDING_DIM, Embedding
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.guidebook_name import GuidebookName
from domain.value_objects.ip_hash import IpHash
from domain.value_objects.lead_flow import LeadFlow
from domain.value_objects.lead_id import LeadId
from domain.value_objects.magic_link import MagicLink

IP = IpHash("0123456789abcdef" * 4)


def make_embedding(seed: int = 0) -> Embedding:
    """Return a valid L2-normalized one-hot embedding (norm == 1.0)."""
    vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    vector[seed % EMBEDDING_DIM] = np.float32(1.0)
    return Embedding(vector=vector)


def make_guidebook_id() -> GuidebookId:
    """Return a fresh ``GuidebookId``."""
    return GuidebookId.new()


def make_magic_link(token: str = "tok-abc") -> MagicLink:
    """Return a ``MagicLink`` wrapping ``token``."""
    return MagicLink(value=SecretStr(token))


def make_lead(
    *,
    email: str = "host@example.com",
    magic_link: MagicLink | None = None,
    flow: LeadFlow = LeadFlow.GUIDEBOOK,
    guidebook_id: GuidebookId | None = None,
    last_seen_at: datetime | None = None,
) -> Lead:
    """Build a persisted-style ``Lead`` (defaults to an active magic link, now timestamps)."""
    now = datetime.now(tz=UTC)
    return Lead.from_repo(
        id=LeadId.new(),
        email=Email(email),
        magic_link=magic_link if magic_link is not None else make_magic_link(),
        captured_at=now,
        last_seen_at=last_seen_at if last_seen_at is not None else now,
        flow=flow,
        guidebook_id=guidebook_id,
        ip_hash=IP,
        ua_short=None,
    )


def make_guidebook(
    *, name: str = "My Place", last_accessed_at: datetime | None = None
) -> Guidebook:
    """Build a ``Guidebook`` via ``create``; optionally override ``last_accessed_at``."""
    guidebook = Guidebook.create(name=GuidebookName(name), ip_hash=IP)
    if last_accessed_at is not None:
        guidebook.last_accessed_at = last_accessed_at
    return guidebook


def make_chunk(
    guidebook_id: GuidebookId,
    ordinal: int = 0,
    text: str = "chunk text",
    page: int | None = None,
) -> Chunk:
    """Build a ``Chunk`` with a valid embedding for ``guidebook_id``."""
    return Chunk.create(
        guidebook_id=guidebook_id,
        ordinal=ordinal,
        text=text,
        page=page,
        embedding=make_embedding(ordinal),
    )

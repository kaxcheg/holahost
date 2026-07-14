from __future__ import annotations

import numpy as np
import pytest

from domain.entities.chunk import Chunk
from domain.entities.guidebook import Guidebook
from domain.value_objects.embedding import Embedding
from domain.value_objects.guidebook_name import GuidebookName
from domain.value_objects.ip_hash import IpHash
from infrastructure.db.sqlalchemy.postgres_chunks_repo import PostgresChunksRepo
from infrastructure.db.sqlalchemy.postgres_guidebooks_repo import PostgresGuidebooksRepo
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


def _unit_embedding(seed: int) -> Embedding:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(384).astype(np.float32)
    v /= np.linalg.norm(v)
    return Embedding(vector=v.astype(np.float32))


@pytest.mark.integration
def test_bulk_add_then_list_ordered(uow: PostgresUnitOfWork) -> None:
    gb = Guidebook.create(name=GuidebookName("G"), ip_hash=IpHash("0" * 64))
    chunks = [
        Chunk.create(
            guidebook_id=gb.id, ordinal=i, text=f"t{i}", page=i, embedding=_unit_embedding(i)
        )
        for i in range(3)
    ]
    with uow.transaction():
        PostgresGuidebooksRepo(uow).add(gb)
        PostgresChunksRepo(uow).bulk_add(chunks)
    with uow.transaction():
        loaded = PostgresChunksRepo(uow).list_for_guidebook(gb.id)
    assert [c.ordinal for c in loaded] == [0, 1, 2]
    assert loaded[0].text == "t0"
    # Page provenance round-trips through the `page` column — proves D7=A: a fresh DB's
    # metadata.create_all materialises the new column (no separate migration), and the
    # repo Data Mapper writes/reads it (B-38…B-45 §2.5).
    assert [c.page for c in loaded] == [0, 1, 2]
    assert np.allclose(loaded[1].embedding.vector, chunks[1].embedding.vector)


@pytest.mark.integration
def test_bulk_add_empty_is_noop(uow: PostgresUnitOfWork) -> None:
    with uow.transaction():
        PostgresChunksRepo(uow).bulk_add([])  # no error, no-op

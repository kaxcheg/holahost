import numpy as np

from domain.value_objects.embedding import EMBEDDING_DIM
from infrastructure.embedding.fastembed_embedding_model import _to_embedding


def test_to_embedding_normalizes_to_unit_norm() -> None:
    raw = np.full((EMBEDDING_DIM,), 3.0, dtype=np.float32)  # norm != 1
    emb = _to_embedding(raw)
    assert abs(float(np.linalg.norm(emb.vector)) - 1.0) <= 1e-3
    assert emb.vector.dtype == np.dtype(np.float32)

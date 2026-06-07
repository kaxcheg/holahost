import numpy as np
import numpy.typing as npt
import pytest

from domain.value_objects.embedding import EMBEDDING_DIM, Embedding


def _normalized() -> npt.NDArray[np.float32]:
    v = np.linspace(0.1, 1.0, EMBEDDING_DIM, dtype=np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


class TestEmbedding:
    def test_accepts_valid_vector(self) -> None:
        emb = Embedding(_normalized())
        assert emb.vector.shape == (EMBEDDING_DIM,)
        assert emb.vector.dtype == np.dtype(np.float32)

    def test_bytes_round_trip(self) -> None:
        emb = Embedding(_normalized())
        restored = Embedding.from_bytes(emb.to_bytes())
        assert np.array_equal(restored.vector, emb.vector)

    def test_rejects_wrong_shape(self) -> None:
        with pytest.raises(ValueError):
            Embedding(np.zeros(10, dtype=np.float32))

    def test_rejects_wrong_dtype(self) -> None:
        bad = _normalized().astype(np.float64)
        with pytest.raises(ValueError):
            Embedding(bad)  # type: ignore[arg-type]

    def test_rejects_non_normalized(self) -> None:
        with pytest.raises(ValueError):
            Embedding(np.full(EMBEDDING_DIM, 1.0, dtype=np.float32))

    def test_from_bytes_rejects_wrong_length(self) -> None:
        with pytest.raises(ValueError):
            Embedding.from_bytes(b"\x00\x00\x00")

    def test_rejects_nan_vector(self) -> None:
        # all-NaN passes the norm check (abs(nan - 1.0) > 1e-3 is False) — finiteness guard.
        with pytest.raises(ValueError):
            Embedding(np.full(EMBEDDING_DIM, np.nan, dtype=np.float32))

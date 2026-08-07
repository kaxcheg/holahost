import math

import pytest

from domain.value_objects.embedding import EMBEDDING_DIM, Embedding


def _unit_vector(dim: int = EMBEDDING_DIM) -> tuple[float, ...]:
    # A trivial L2-normalized vector: one axis = 1.0, the rest = 0.0.
    return tuple(1.0 if i == 0 else 0.0 for i in range(dim))


class TestEmbedding:
    def test_accepts_a_normalized_vector_of_the_right_dimension(self) -> None:
        vec = _unit_vector()
        assert Embedding(vec).value == vec

    def test_rejects_wrong_dimension(self) -> None:
        with pytest.raises(ValueError, match="dimension"):
            Embedding(_unit_vector(dim=EMBEDDING_DIM - 1))

    def test_rejects_non_finite_values(self) -> None:
        bad = list(_unit_vector())
        bad[1] = math.nan
        with pytest.raises(ValueError, match="finite"):
            Embedding(tuple(bad))

    def test_rejects_a_vector_not_l2_normalized(self) -> None:
        not_normalized = tuple(2.0 if i == 0 else 0.0 for i in range(EMBEDDING_DIM))
        with pytest.raises(ValueError, match="norm"):
            Embedding(not_normalized)

    def test_is_hashable_and_comparable_by_value(self) -> None:
        vec = _unit_vector()
        assert Embedding(vec) == Embedding(vec)
        assert hash(Embedding(vec)) == hash(Embedding(vec))

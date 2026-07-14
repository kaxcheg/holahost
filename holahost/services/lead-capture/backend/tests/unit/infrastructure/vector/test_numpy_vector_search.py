from infrastructure.vector.numpy_vector_search import NumpyVectorSearch
from tests._support.builders import make_chunk, make_embedding, make_guidebook_id


def test_top_k_orders_by_descending_cosine() -> None:
    gid = make_guidebook_id()
    chunks = [make_chunk(gid, ordinal=i) for i in range(4)]  # embeddings = one-hot e_i
    out = NumpyVectorSearch().top_k(query=make_embedding(2), chunks=chunks, k=2)
    assert out[0].ordinal == 2  # exact match scores 1.0
    assert len(out) == 2


def test_k_larger_than_population_returns_all() -> None:
    gid = make_guidebook_id()
    chunks = [make_chunk(gid, ordinal=i) for i in range(3)]
    assert len(NumpyVectorSearch().top_k(make_embedding(0), chunks, k=10)) == 3


def test_empty_or_nonpositive_k_returns_empty() -> None:
    gid = make_guidebook_id()
    assert NumpyVectorSearch().top_k(make_embedding(0), [], k=5) == []
    assert NumpyVectorSearch().top_k(make_embedding(0), [make_chunk(gid)], k=0) == []

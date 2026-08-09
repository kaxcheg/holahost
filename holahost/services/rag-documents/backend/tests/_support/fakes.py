"""Hand-written fakes for application-layer ports, used across use-case tests."""

from __future__ import annotations

from types import TracebackType

from application.ports.ingestion import TextFragment
from application.ports.vector import SearchHit
from domain.entities.chunk import Chunk
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject


class FakeFileParser:
    """Returns a preset list of fragments, or raises a preset exception."""

    def __init__(
        self, fragments: list[TextFragment] | None = None, *, error: Exception | None = None
    ) -> None:
        self._fragments = fragments if fragments is not None else []
        self._error = error

    def parse(self, content: bytes, mime_type: MimeType) -> list[TextFragment]:
        if self._error is not None:
            raise self._error
        return self._fragments


class FakeTextChunker:
    """Returns its input fragments unchanged, unless a preset output is given."""

    def __init__(self, chunks: list[TextFragment] | None = None) -> None:
        self._chunks = chunks

    def split(self, fragments: list[TextFragment]) -> list[TextFragment]:
        return self._chunks if self._chunks is not None else fragments


class FakeEmbeddingModel:
    """Returns one preset embedding per input text, and for any query."""

    def __init__(self, embedding: Embedding) -> None:
        self._embedding = embedding

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        return [self._embedding for _ in texts]

    def embed_query(self, text: str) -> Embedding:
        return self._embedding


class FakeDocumentsRepo:
    """In-memory ``DocumentsRepo`` keyed by document id, owner-scoped reads."""

    def __init__(self, documents: list[Document] | None = None) -> None:
        self._by_id: dict[DocumentId, Document] = {d.id: d for d in (documents or [])}
        self.added: list[Document] = []
        self.updated: list[Document] = []
        self.deleted: list[DocumentId] = []

    def add(self, document: Document, owner: OwnerSubject) -> None:
        assert document.owner == owner, "add() called with mismatched owner"
        self._by_id[document.id] = document
        self.added.append(document)

    def get(
        self, document_id: DocumentId, owner: OwnerSubject, *, lock: bool = False
    ) -> Document | None:
        document = self._by_id.get(document_id)
        if document is None or document.owner != owner:
            return None
        return document

    def update(self, document: Document, owner: OwnerSubject) -> None:
        assert document.owner == owner, "update() called with mismatched owner"
        self._by_id[document.id] = document
        self.updated.append(document)

    def delete(self, document_id: DocumentId, owner: OwnerSubject) -> None:
        del self._by_id[document_id]
        self.deleted.append(document_id)


class FakeChunksRepo:
    """In-memory ``ChunksRepo`` keyed by document id."""

    def __init__(self) -> None:
        self._by_document: dict[DocumentId, list[Chunk]] = {}
        self.added: list[Chunk] = []
        self.deleted_documents: list[DocumentId] = []

    def add_many(self, chunks: list[Chunk], owner: OwnerSubject) -> None:
        for chunk in chunks:
            self._by_document.setdefault(chunk.document_id, []).append(chunk)
        self.added.extend(chunks)

    def delete_by_document(self, document_id: DocumentId, owner: OwnerSubject) -> None:
        self._by_document.pop(document_id, None)
        self.deleted_documents.append(document_id)


class FakeVectorSearch:
    """Returns a preset list of hits regardless of the query."""

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self._hits = hits if hits is not None else []

    def top_k(
        self, document_id: DocumentId, query: Embedding, k: int, threshold: float
    ) -> list[SearchHit]:
        return self._hits


class FakeUnitOfWork:
    """A real context manager: records commits/rollbacks, does not swallow exceptions."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self) -> FakeUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

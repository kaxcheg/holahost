"""Hand-written fakes for application-layer ports, used across use-case tests."""

from __future__ import annotations

from types import TracebackType

from application.ports.ingestion import TextFragment
from application.ports.repos import DocumentsRepo
from application.ports.vector import SearchHit, VectorSearch
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject

_DEFAULT_OWNER = OwnerSubject("user-123")  # matches every test command's owner in this suite


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


class FakeDocumentsRepo(DocumentsRepo):
    """In-memory ``DocumentsRepo``, owner bound at construction like the real
    adapter — defaults to ``_DEFAULT_OWNER`` since every command in this test suite
    uses that owner, so most call sites never need to pass one explicitly.

    Also implements ``DocumentsRepoFactory`` via ``__call__``: an instance can be
    passed directly wherever a use case expects a factory (``owner`` is already
    bound, so the call just returns ``self``), no separate factory needed in tests.
    """

    def __init__(
        self, documents: list[Document] | None = None, *, owner: OwnerSubject = _DEFAULT_OWNER
    ) -> None:
        super().__init__(uow=FakeUnitOfWork(), owner=owner)
        self._by_id: dict[DocumentId, Document] = {d.id: d for d in (documents or [])}
        self.added: list[Document] = []
        self.updated: list[Document] = []
        self.deleted: list[DocumentId] = []

    def __call__(self, owner: OwnerSubject) -> DocumentsRepo:
        return self

    def _bind_owner(self) -> None:
        pass  # no real RLS to simulate — filtering below is against self._owner directly

    def _add_impl(self, document: Document) -> None:
        assert document.owner == self._owner, "add() called with mismatched owner"
        self._by_id[document.id] = document
        self.added.append(document)

    def _get_impl(self, document_id: DocumentId, *, lock: bool) -> Document | None:
        document = self._by_id.get(document_id)
        if document is None or document.owner != self._owner:
            return None
        return document

    def _update_impl(self, document: Document) -> None:
        assert document.owner == self._owner, "update() called with mismatched owner"
        self._by_id[document.id] = document
        self.updated.append(document)

    def _delete_impl(self, document_id: DocumentId) -> None:
        self._by_id.pop(document_id, None)
        self.deleted.append(document_id)


class FakeVectorSearch(VectorSearch):
    """Returns a preset list of hits regardless of the query. Owner bound at
    construction like ``FakeDocumentsRepo``; also usable directly as a
    ``VectorSearchFactory`` via ``__call__``."""

    def __init__(
        self, hits: list[SearchHit] | None = None, *, owner: OwnerSubject = _DEFAULT_OWNER
    ) -> None:
        super().__init__(uow=FakeUnitOfWork(), owner=owner)
        self._hits = hits if hits is not None else []

    def __call__(self, owner: OwnerSubject) -> VectorSearch:
        return self

    def _bind_owner(self) -> None:
        pass

    def _top_k_impl(
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

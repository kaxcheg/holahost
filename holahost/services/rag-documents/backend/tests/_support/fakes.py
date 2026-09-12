"""Hand-written fakes for application-layer ports, used across use-case tests."""

from __future__ import annotations

from types import TracebackType

from holahost_http import RateLimitExceededError

from application.ports.ingestion import TextFragment
from application.ports.repos import DocumentsRepo
from application.ports.vector import SearchHit, VectorSearch
from domain.entities.document import Document
from domain.value_objects.document_id import DocumentId
from domain.value_objects.embedding import Embedding
from domain.value_objects.mime_type import MimeType
from domain.value_objects.owner_subject import OwnerSubject

_DEFAULT_OWNER = OwnerSubject("user-123")  # matches every test command's owner in this suite


def _require_open_unit_of_work(port: str) -> None:
    """Fail loudly on a port call made outside an open ``UnitOfWork``.

    The rule these fakes exist to protect: every ``DocumentsRepo`` and ``VectorSearch``
    call runs inside an explicit ``with uow:``. Without this check a use case that
    dropped its ``with self.uow:`` would pass the whole unit suite and fail only against
    a real connection.
    """
    if not FakeUnitOfWork.any_open():
        raise AssertionError(
            f"{port} call outside an open UnitOfWork — every call must run "
            "inside an explicit `with uow:`"
        )


class FakeFileParser:
    """Returns a preset list of fragments, or raises a preset exception."""

    def __init__(
        self, fragments: list[TextFragment] | None = None, *, error: Exception | None = None
    ) -> None:
        self._fragments = fragments if fragments is not None else []
        self._error = error
        self.calls = 0

    def parse(self, content: bytes, mime_type: MimeType) -> list[TextFragment]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._fragments


class FakeTextChunker:
    """Returns its input fragments unchanged, unless a preset output is given."""

    def __init__(self, chunks: list[TextFragment] | None = None) -> None:
        self._chunks = chunks
        self.calls = 0

    def split(self, fragments: list[TextFragment]) -> list[TextFragment]:
        self.calls += 1
        return self._chunks if self._chunks is not None else fragments


class FakeEmbeddingModel:
    """Returns one preset embedding per input text, and for any query."""

    def __init__(self, embedding: Embedding) -> None:
        self._embedding = embedding
        # Call counters, so a test can assert an expensive port was never reached — the
        # only way to pin *ordering* rather than just the resulting exception.
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[Embedding]:
        self.calls += 1
        return [self._embedding for _ in texts]

    def embed_query(self, text: str) -> Embedding:
        self.calls += 1
        return self._embedding


class FakeDocumentsRepo(DocumentsRepo):
    """In-memory ``DocumentsRepo``, owner bound at construction like the real
    adapter — defaults to ``_DEFAULT_OWNER`` since every command in this test suite
    uses that owner, so most call sites never need to pass one explicitly.

    Also implements ``DocumentsRepoFactory`` via ``__call__``, which **rebinds** the
    owner exactly as the real factory does by constructing a repo for it. Returning
    ``self`` while ignoring the argument would make the owner-scoping contract
    untestable: a use case that asked the factory for the wrong subject would get a
    repo scoped to the right one anyway, and the isolation rule would hold only in
    comments.
    """

    def __init__(
        self,
        documents: list[Document] | None = None,
        *,
        owner: OwnerSubject = _DEFAULT_OWNER,
        uow: FakeUnitOfWork | None = None,
    ) -> None:
        super().__init__(uow=uow or FakeUnitOfWork(), owner=owner)
        self._by_id: dict[DocumentId, Document] = {d.id: d for d in (documents or [])}
        self.added: list[Document] = []
        self.updated: list[Document] = []
        self.deleted: list[DocumentId] = []
        self.factory_owners: list[OwnerSubject] = []

    def __call__(self, owner: OwnerSubject) -> DocumentsRepo:
        self.factory_owners.append(owner)
        self._owner = owner
        return self

    def _bind_owner(self) -> None:
        # No real RLS to simulate — filtering below is against self._owner directly.
        # What this does enforce is the other half of the contract: every repository
        # call runs inside an explicit `with uow:`.
        _require_open_unit_of_work("DocumentsRepo")

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
    """Returns a preset list of hits for the owner they were registered under, and
    nothing for anyone else. Owner bound at construction and rebound by ``__call__``,
    exactly like ``FakeDocumentsRepo`` and for the same reason: hits returned
    regardless of ``owner`` would make the isolation contract unfalsifiable.

    Records every call, so a test can pin what the use case actually asked for —
    ``document_id``, ``k`` and ``threshold`` included."""

    def __init__(
        self,
        hits: list[SearchHit] | None = None,
        *,
        owner: OwnerSubject = _DEFAULT_OWNER,
        uow: FakeUnitOfWork | None = None,
    ) -> None:
        super().__init__(uow=uow or FakeUnitOfWork(), owner=owner)
        self._hits = hits if hits is not None else []
        self._hits_owner = owner
        self.factory_owners: list[OwnerSubject] = []
        self.calls: list[tuple[DocumentId, int, float]] = []

    def __call__(self, owner: OwnerSubject) -> VectorSearch:
        self.factory_owners.append(owner)
        self._owner = owner
        return self

    def _bind_owner(self) -> None:
        _require_open_unit_of_work("VectorSearch")

    def _top_k_impl(
        self, document_id: DocumentId, query: Embedding, k: int, threshold: float
    ) -> list[SearchHit]:
        self.calls.append((document_id, k, threshold))
        if self._owner != self._hits_owner:
            # What RLS does in production: another subject's chunks are simply not
            # visible, and an empty result is a valid, non-error outcome.
            return []
        return self._hits


class FakeRateLimiter:
    """``holahost_http.RateLimiter`` fake — trips on demand, not on real counting."""

    def __init__(self, *, should_raise: bool = False, retry_after: int = 30) -> None:
        self.should_raise = should_raise
        self.retry_after = retry_after
        self.calls: list[tuple[str, str, str, bool]] = []

    def check(self, *, client_id: str, subject: str, bucket: str, is_service: bool) -> None:
        self.calls.append((client_id, subject, bucket, is_service))
        if self.should_raise:
            raise RateLimitExceededError(retry_after=self.retry_after)


class FakeUnitOfWork:
    """A real context manager: records commits/rollbacks, does not swallow exceptions.

    Also tracks, class-wide, how many of these are currently open — which is what
    ``_require_open_unit_of_work`` reads. Class-wide rather than per instance because
    the rule is "no repository call outside a transaction", not "inside this
    particular object": a unit test has exactly one unit of work in play, and keying
    the check on identity would mean threading it through all ~40 fake constructions
    to assert something none of them is actually about.
    """

    _open = 0

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    @classmethod
    def any_open(cls) -> bool:
        return cls._open > 0

    def __enter__(self) -> FakeUnitOfWork:
        FakeUnitOfWork._open += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        FakeUnitOfWork._open -= 1
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

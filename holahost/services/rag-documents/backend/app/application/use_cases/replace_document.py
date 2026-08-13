"""UC-R2: replace a document's content (spec §8.3)."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.documents import DocumentView, ReplaceDocumentCmd
from application.exceptions import (
    EmptyDocumentError,
    InvalidPayloadError,
    NotFoundError,
    ParsedTextTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    UploadTooLargeError,
)
from application.limits import MAX_PARSED_TEXT_LENGTH, MAX_UPLOAD_SIZE, MIN_EXTRACTED_TEXT_CHARS
from application.ports.embedding import EmbeddingModel
from application.ports.ingestion import FileParser, TextChunker
from application.ports.repos import DocumentsRepoFactory
from application.ports.uow import UnitOfWork
from application.use_cases._internal_errors import wrap_value_error
from application.use_cases._retry import retry_on_concurrent_update
from domain.entities.chunk import Chunk
from domain.entities.document import MAX_CHUNKS_PER_DOCUMENT, Document
from domain.exceptions import DomainValidationError
from domain.value_objects.chunk_index import ChunkIndex
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import ALLOWED_MIME_TYPES, MimeType
from domain.value_objects.owner_subject import OwnerSubject


@dataclass
class ReplaceDocumentUseCase:
    """UC-R2: atomically replace a document's content, keeping its id (A-6)."""

    parser: FileParser
    chunker: TextChunker
    embedder: EmbeddingModel
    documents_repo_factory: DocumentsRepoFactory
    uow: UnitOfWork

    @wrap_value_error
    def execute(self, cmd: ReplaceDocumentCmd) -> DocumentView:
        """Run the replace pipeline and persist the result under the same id.

        :raises ApplicationError: wraps a bare ``ValueError`` from a VO/entity
            construction — an internal invariant violation, never client-fixable.
        :raises NotFoundError: the document does not exist, belongs to another owner,
            or (from the locked recheck) was deleted concurrently after the initial
            unlocked check passed.
        :raises UnsupportedMediaTypeError: see `CreateDocumentUseCase.execute`.
        :raises InvalidPayloadError: `cmd.name` (if given) is empty, too long, or has
            control chars.
        :raises UploadTooLargeError: see `CreateDocumentUseCase.execute`.
        :raises DocumentParseError: conscious pass-through from `FileParser`.
        :raises EmptyDocumentError: see `CreateDocumentUseCase.execute`.
        :raises ParsedTextTooLargeError: see `CreateDocumentUseCase.execute`.
        :raises TooManyChunksError: see `CreateDocumentUseCase.execute`.
        :raises EmbeddingFailedError: conscious pass-through.
        :raises StorageUnavailableError: conscious pass-through.
        :raises ConcurrentUpdateError: re-raised only after the locked write has
            already been retried twice (§8.6) — the pipeline itself is not retried,
            its output is already computed.
        :raises IntegrityError: conscious pass-through.
        """
        owner = OwnerSubject(cmd.owner)
        document_id = DocumentId.from_str(cmd.document_id)
        documents_repo = self.documents_repo_factory(owner)

        # Unlocked pre-check: cheap, may be stale — re-verified under lock below,
        # so a false positive here just means wasted pipeline work, not corruption.
        # Still runs inside a transaction — every DocumentsRepo call does (§8.0) —
        # a short one of its own, distinct from the locked write's transaction below.
        with self.uow:
            existing = documents_repo.get(document_id)
            if existing is None:
                raise NotFoundError

        try:
            mime_type = MimeType(cmd.mime_type)
        except DomainValidationError as e:
            raise UnsupportedMediaTypeError(allowed=tuple(sorted(ALLOWED_MIME_TYPES))) from e

        if len(cmd.content) > MAX_UPLOAD_SIZE:
            raise UploadTooLargeError(limit=MAX_UPLOAD_SIZE, actual=len(cmd.content))

        fragments = self.parser.parse(cmd.content, mime_type)

        total_chars = sum(len(f.text) for f in fragments)
        if total_chars < MIN_EXTRACTED_TEXT_CHARS:
            raise EmptyDocumentError(min_chars=MIN_EXTRACTED_TEXT_CHARS)
        if total_chars > MAX_PARSED_TEXT_LENGTH:
            raise ParsedTextTooLargeError(limit=MAX_PARSED_TEXT_LENGTH, actual=total_chars)

        chunks = self.chunker.split(fragments)
        if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
            raise TooManyChunksError(limit=MAX_CHUNKS_PER_DOCUMENT, actual=len(chunks))

        embeddings = self.embedder.embed_texts([c.text for c in chunks])

        new_name: DocumentName | None = None
        if cmd.name is not None:
            try:
                new_name = DocumentName(cmd.name)
            except DomainValidationError as e:
                raise InvalidPayloadError(field=e.field or "name") from e

        new_chunks = [
            Chunk.create(document_id, ChunkIndex(i), fragment.text, embedding, fragment.page)
            for i, (fragment, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ]

        def _write() -> Document:
            with self.uow:
                # Locked re-check: guards against a concurrent replace/delete that
                # landed between the pre-check above and here.
                document = documents_repo.get(document_id, lock=True)
                if document is None:
                    raise NotFoundError
                if new_name is not None:
                    document.rename(new_name)
                try:
                    document.replace_content(mime_type, new_chunks)
                except DomainValidationError:
                    raise TooManyChunksError(
                        limit=MAX_CHUNKS_PER_DOCUMENT, actual=len(chunks)
                    ) from None
                documents_repo.update(document)
                return document

        document = retry_on_concurrent_update(_write)
        return DocumentView.of(document)

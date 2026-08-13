"""UC-R1: create a new document (spec §8.2)."""

from __future__ import annotations

from dataclasses import dataclass

from application.dto.documents import CreateDocumentCmd, DocumentView
from application.exceptions import (
    EmptyDocumentError,
    InvalidPayloadError,
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
from domain.entities.chunk import Chunk
from domain.entities.document import MAX_CHUNKS_PER_DOCUMENT, Document
from domain.exceptions import DomainValidationError
from domain.value_objects.chunk_index import ChunkIndex
from domain.value_objects.document_id import DocumentId
from domain.value_objects.document_name import DocumentName
from domain.value_objects.mime_type import ALLOWED_MIME_TYPES, MimeType
from domain.value_objects.owner_subject import OwnerSubject


@dataclass
class CreateDocumentUseCase:
    """UC-R1: parse, chunk, embed, then write a document and its chunks atomically."""

    parser: FileParser
    chunker: TextChunker
    embedder: EmbeddingModel
    documents_repo_factory: DocumentsRepoFactory
    uow: UnitOfWork

    @wrap_value_error
    def execute(self, cmd: CreateDocumentCmd) -> DocumentView:
        """Run the create pipeline and persist the result.

        :raises ApplicationError: wraps a bare ``ValueError`` from a VO/entity
            construction — an internal invariant violation, never client-fixable.
        :raises UnsupportedMediaTypeError: `cmd.mime_type` is not supported, or (from
            `FileParser` directly) the file's sniffed content does not match it.
        :raises InvalidPayloadError: `cmd.name` is empty, too long, or has control chars.
        :raises UploadTooLargeError: `cmd.content` exceeds `MAX_UPLOAD_SIZE`.
        :raises DocumentParseError: conscious pass-through from `FileParser` — the
            file is corrupted or cannot be parsed.
        :raises EmptyDocumentError: fewer than `MIN_EXTRACTED_TEXT_CHARS` were extracted.
        :raises ParsedTextTooLargeError: parsed text exceeds `MAX_PARSED_TEXT_LENGTH`.
        :raises TooManyChunksError: more than `MAX_CHUNKS_PER_DOCUMENT` chunks resulted.
        :raises EmbeddingFailedError: conscious pass-through — not retried in-request (§8.6).
        :raises StorageUnavailableError: conscious pass-through.
        :raises ConcurrentUpdateError: conscious pass-through — unlike replace/delete,
            create has no pre-existing row to lock and conflict on, so §8.6 does not
            call for a retry here.
        :raises IntegrityError: conscious pass-through — an internal defect.
        """
        try:
            mime_type = MimeType(cmd.mime_type)
        except DomainValidationError as e:
            raise UnsupportedMediaTypeError(allowed=tuple(sorted(ALLOWED_MIME_TYPES))) from e

        try:
            name = DocumentName(cmd.name)
        except DomainValidationError as e:
            raise InvalidPayloadError(field=e.field or "name") from e

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

        owner = OwnerSubject(cmd.owner)
        document_id = DocumentId.new()  # chunks need the id before the document exists
        new_chunks = [
            Chunk.create(document_id, ChunkIndex(i), fragment.text, embedding, fragment.page)
            for i, (fragment, embedding) in enumerate(zip(chunks, embeddings, strict=True))
        ]

        try:
            document = Document.create(document_id, owner, name, mime_type, new_chunks)
        except DomainValidationError:
            # Backstop: the check above already enforces len(chunks) <= MAX_CHUNKS_PER_DOCUMENT,
            # so this should be unreachable — kept because Document.create's own contract
            # declares it a possible client-facing raise (domain/entities/document.py).
            raise TooManyChunksError(limit=MAX_CHUNKS_PER_DOCUMENT, actual=len(chunks)) from None

        documents_repo = self.documents_repo_factory(owner)
        with self.uow:
            documents_repo.add(document)  # no lock: fresh row, nothing to race

        return DocumentView.of(document)

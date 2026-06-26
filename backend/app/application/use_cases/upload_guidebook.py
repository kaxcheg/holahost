from __future__ import annotations

from dataclasses import dataclass

from application.dto.ingestion import IngestionResult, UploadGuidebookCmd
from application.exceptions import (
    EmptyDocumentError,
    InvalidMagicLinkError,
    PayloadTooLargeError,
    TooManyChunksError,
    UnsupportedMediaTypeError,
    magic_link_validation,
    payload_validation,
)
from application.ports.embedding import EmbeddingModel
from application.ports.ingestion import FileParser, TextChunker
from application.ports.rate import RateLimiter, RateLimitScope
from application.ports.repos import ChunksRepo, GuidebooksRepo, LeadsRepo
from application.ports.uow import UnitOfWork
from config.config import Settings
from domain.entities.chunk import Chunk
from domain.entities.guidebook import Guidebook
from domain.value_objects.guidebook_name import GuidebookName
from domain.value_objects.ip_hash import IpHash
from domain.value_objects.magic_link import MagicLink


@dataclass
class UploadGuidebookUseCase:
    """Parse → chunk → embed an upload and (re)attach it to the lead's guidebook (spec §9.4)."""

    rate: RateLimiter
    leads_repo: LeadsRepo
    guidebooks_repo: GuidebooksRepo
    chunks_repo: ChunksRepo
    parser: FileParser
    chunker: TextChunker
    embedder: EmbeddingModel
    uow: UnitOfWork
    settings: Settings

    def execute(self, cmd: UploadGuidebookCmd) -> IngestionResult:
        """Validate, resolve, run ingestion outside the UoW, then write atomically.

        The magic link is resolved twice: an unlocked pre-check before the CPU-bound
        parse/chunk/embed (no lock held across it), then a locked holder re-read
        (``get_by_magic_link_for_update``) opening the write transaction (§9.4 / §9.0). On replace
        the order is add new → repoint lead → delete old guidebook (cascading its chunks), so the
        lead never transiently points at a missing guidebook and the old row is removed only after
        nothing references it.

        Args:
            cmd: The upload command (magic link, ip hash, name, file bytes, MIME type).

        Returns:
            The created guidebook's id, echoed name, and creation timestamp.

        :raises RateLimitExceededError: per-ip or per-magic-link cap exceeded (§9.8).
        :raises PayloadTooLargeError: file over the byte-size cap (§9.8).
        :raises TooManyChunksError: parsed document exceeds the chunk-count cap (§9.8).
        :raises UnsupportedMediaTypeError: MIME type not allowed (§9.8).
        :raises InvalidPayloadError: empty/invalid name primitive (§9.0).
        :raises InvalidMagicLinkError: token empty/invalid, unknown, or expired (§9.8).
        :raises EmptyDocumentError: file under the byte minimum, extracted text below the minimum,
            or too few chunks (§9.8).
        """
        with self.uow.transaction():
            self.rate.check_and_increment(RateLimitScope.IP, cmd.ip_hash)

        # byte-size guard (min/max) before any parse/chunk work (§9.4 multi-level guard)
        if len(cmd.file_bytes) > self.settings.max_upload_size_bytes:
            raise PayloadTooLargeError(max_bytes=self.settings.max_upload_size_bytes)
        if len(cmd.file_bytes) < self.settings.min_upload_size_bytes:
            raise EmptyDocumentError()
        if cmd.mime_type not in self.settings.allowed_mime_types:
            raise UnsupportedMediaTypeError(allowed=sorted(self.settings.allowed_mime_types))

        # primitive -> VO before CPU-bound work. An empty/invalid magic link is an invalid
        # credential → 401 (magic_link_validation); GuidebookName raises DomainValidationError
        # (reason="empty"/"too_long", §7.2.6/§10.8) which payload_validation maps to 422.
        with magic_link_validation():
            magic_link = MagicLink(cmd.magic_link)
        with payload_validation():
            name = GuidebookName(cmd.name)
        # ip_hash is server-derived (sha256(ip||salt)); a bad value is our bug → 500, not a 422,
        # so it is built outside payload_validation (which converts client-payload errors).
        ip_hash = IpHash(cmd.ip_hash)

        with self.uow.transaction():
            lead = self.leads_repo.get_by_magic_link(magic_link)
            if lead is None:
                raise InvalidMagicLinkError()
            self.rate.check_and_increment(RateLimitScope.MAGIC_LINK, str(lead.id))

        segments = self.parser.parse(cmd.file_bytes, cmd.mime_type)
        if sum(len(s.text) for s in segments) < self.settings.min_extracted_text_chars:
            raise EmptyDocumentError()
        # chunk-count guard (min/max). The chunker contract guarantees per-chunk token length
        # (TextChunker port): its window must be <= the embedding model's max input, else the
        # embedder silently truncates (§2.5) — enforced by the chunker impl, not measurable here.
        chunked = self.chunker.chunk(segments)
        if len(chunked) > self.settings.max_chunks_per_guidebook:
            raise TooManyChunksError(max_chunks=self.settings.max_chunks_per_guidebook)
        if len(chunked) < self.settings.min_chunks_per_guidebook:
            raise EmptyDocumentError()
        embeddings = self.embedder.embed_many([c.text for c in chunked])

        guidebook = Guidebook.create(name=name, ip_hash=ip_hash)
        new_chunks: list[Chunk] = [
            Chunk.create(
                guidebook_id=guidebook.id,
                ordinal=i,
                text=c.text,
                page=c.page,
                embedding=e,
            )
            for i, (c, e) in enumerate(zip(chunked, embeddings, strict=True))
        ]

        with self.uow.transaction():
            lead = self.leads_repo.get_by_magic_link_for_update(magic_link)
            if lead is None:
                raise InvalidMagicLinkError()
            # add new -> repoint lead -> delete old (§9.4): the lead never transiently points at a
            # missing guidebook, and the old row is deleted only after nothing references it. All
            # under the lead holder lock, so the guidebook delete is a plain cascade with no own lock.
            old_guidebook_id = lead.guidebook_id
            self.guidebooks_repo.add(guidebook)
            self.chunks_repo.bulk_add(new_chunks)
            lead.attach_guidebook(guidebook.id)
            self.leads_repo.update(lead)
            if old_guidebook_id is not None:
                self.guidebooks_repo.delete(old_guidebook_id)

        return IngestionResult(
            guidebook_id=str(guidebook.id),
            name=guidebook.name.value,
            created_at=guidebook.created_at.isoformat(),
        )

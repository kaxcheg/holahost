"""Cold-start preload of the sample guidebook into searchable chunks (spec §8.6 / §8.8).

Reuses the real ingestion chain (parse → chunk → embed) so the sample's chunk boundaries and
tokenization match real uploads. The raw bytes come from an injected ``SampleGuidebookSource`` (the
guidebook is business data in ``docs/``, path via ``Settings.sample_guidebook_path``), so this module
hardcodes no file location. Runs once on cold start; SnapStart freezes the result.
``SampleGenerateUseCase`` searches these chunks directly and ignores ``guidebook_id``, so a fixed
sentinel id is sufficient (C-8 / C-31).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from domain.entities.chunk import Chunk
from domain.value_objects.guidebook_id import GuidebookId

if TYPE_CHECKING:
    from application.ports.embedding import EmbeddingModel
    from application.ports.ingestion import FileParser, TextChunker
    from infrastructure.sample.source import SampleGuidebookSource

SAMPLE_GUIDEBOOK_ID = GuidebookId.from_str("00000000-0000-0000-0000-000000000001")
_SAMPLE_MIME = "text/markdown"


def load_sample_chunks(
    source: SampleGuidebookSource,
    file_parser: FileParser,
    chunker: TextChunker,
    embedder: EmbeddingModel,
) -> list[Chunk]:
    """Parse + chunk + embed the sample guidebook bytes into ``Chunk`` objects.

    Args:
        source: Provides the sample guidebook bytes (``docs/`` file via the Settings path).
        file_parser: Parser for the bytes (markdown → a single segment).
        chunker: Chunker splitting the segment(s) into chunk-sized segments.
        embedder: Embedding model; ``embed_many`` preserves input order.

    Returns:
        Preloaded sample chunks, all under :data:`SAMPLE_GUIDEBOOK_ID`, ordinals 0..n-1.
    """
    segments = file_parser.parse(source.read(), _SAMPLE_MIME)
    chunk_segments = chunker.chunk(segments)
    embeddings = embedder.embed_many([segment.text for segment in chunk_segments])
    return [
        Chunk.create(
            guidebook_id=SAMPLE_GUIDEBOOK_ID,
            ordinal=ordinal,
            text=segment.text,
            page=segment.page,
            embedding=embedding,
        )
        for ordinal, (segment, embedding) in enumerate(zip(chunk_segments, embeddings, strict=True))
    ]

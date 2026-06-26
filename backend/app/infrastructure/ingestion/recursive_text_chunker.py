from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from domain.value_objects.parsed_segment import ParsedSegment


class RecursiveTextChunker:
    """TextChunker adapter over LangChain's RecursiveCharacterTextSplitter (spec §8.2.1, C-04/C-14).

    Wraps each parsed segment in a LangChain ``Document`` carrying minimal ``metadata={"page": …}``
    and runs ``split_documents`` (the idiomatic LangChain path; C-14): the splitter chunks each
    document independently and copies its metadata onto every chunk, so each output chunk inherits its
    source segment's ``page`` (exact provenance, no cross-page overlap; C-05/C-06). The ``Document``
    type never crosses the port boundary — input/output are domain ``ParsedSegment`` objects. Chunk
    length is measured by the injected ``length_function`` — wired in production to the embedding
    model's own tokenizer (``FastEmbedEmbeddingModel.count_tokens``) so every chunk fits
    ``max_chunk_tokens`` (the TextChunker port invariant; C-07). The function is injected (not
    hard-wired) for deterministic unit tests (``length_function=len``).

    Structurally conforms to the TextChunker port (no inheritance): see ``_conforms``.
    """

    def __init__(
        self,
        length_function: Callable[[str], int],
        chunk_window: int,
        chunk_overlap: int,
    ) -> None:
        """Init.

        Args:
            length_function: Token counter; in production the embedder's tokenizer (C-07).
            chunk_window: Max tokens per chunk (``<= max_chunk_tokens``; Settings-validated).
            chunk_overlap: Token overlap between adjacent chunks (``< chunk_window``).
        """
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_window,
            chunk_overlap=chunk_overlap,
            length_function=length_function,
        )

    def chunk(self, segments: list[ParsedSegment]) -> list[ParsedSegment]:
        """Split each segment into token-bounded chunks, preserving page provenance (see port)."""
        documents = [
            Document(page_content=segment.text, metadata={"page": segment.page})
            for segment in segments
        ]
        pieces = self._splitter.split_documents(documents)
        return [
            ParsedSegment(text=piece.page_content, page=piece.metadata["page"])
            for piece in pieces
        ]


if TYPE_CHECKING:
    from application.ports.ingestion import TextChunker

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: RecursiveTextChunker) -> TextChunker:
        return x

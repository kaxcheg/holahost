from __future__ import annotations

from collections.abc import Callable

from langchain_core.documents import Document as LangchainDocument
from langchain_text_splitters import RecursiveCharacterTextSplitter

from application.ports.ingestion import TextFragment
from domain.value_objects.page_number import PageNumber


class RecursiveTextChunker:
    """Adapter for the `TextChunker` port over `RecursiveCharacterTextSplitter`.

    Wraps each fragment in a LangChain `Document` carrying `metadata={"page": ...}` and
    runs `split_documents` — the splitter chunks each document independently, so a chunk
    never crosses a fragment's boundary and inherits its source `page` exactly.
    `length_function` is injected (in production the embedder's own tokenizer via
    `FastembedEmbeddingModel.count_tokens`, wired at composition; tests use `len`) so
    chunk-window guarantees never drift from what the model actually tokenizes.
    """

    def __init__(
        self,
        length_function: Callable[[str], int],
        chunk_window: int,
        chunk_overlap: int,
        max_input_tokens: int | None = None,
    ) -> None:
        """
        Args:
            max_input_tokens: the embedding model's real token ceiling (e.g.
                `FastembedEmbeddingModel.max_input_tokens()`), wired at composition —
                pass it whenever `length_function` counts tokens, so a misconfigured
                `chunk_window` fails loudly here instead of producing chunks that get
                silently truncated at embed time (verified risk, see
                `FastembedEmbeddingModel.count_tokens`'s docstring). `None` (default)
                skips the check — correct for tests using `len` (character count),
                where "tokens" isn't a meaningful unit to compare against at all.

        Raises:
            ValueError: `chunk_window` exceeds `max_input_tokens` — a real chunk
                could never fit in the model's input, not something split_documents
                could route around later.
        """
        if max_input_tokens is not None and chunk_window > max_input_tokens:
            raise ValueError(
                f"chunk_window ({chunk_window}) exceeds the embedding model's "
                f"max_input_tokens ({max_input_tokens}) — chunks this large would be "
                f"silently truncated when embedded, not actually produced at this size"
            )
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_window,
            chunk_overlap=chunk_overlap,
            length_function=length_function,
        )

    def split(self, fragments: list[TextFragment]) -> list[TextFragment]:
        documents = [
            LangchainDocument(page_content=fragment.text, metadata={"page": fragment.page.value})
            for fragment in fragments
        ]
        pieces = self._splitter.split_documents(documents)
        return [
            TextFragment(text=piece.page_content, page=PageNumber(piece.metadata["page"]))
            for piece in pieces
        ]

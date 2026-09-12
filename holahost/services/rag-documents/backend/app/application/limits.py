"""Domain parameters the application layer needs.

Bare module constants rather than injected configuration, matching the domain layer's own
precedent (`MAX_CHUNKS_PER_DOCUMENT` in `domain.entities.document`): these are properties
of the ingestion pipeline itself, not knobs an environment turns.
"""

from __future__ import annotations

MAX_UPLOAD_SIZE = 8 * 1024 * 1024  # 8 MiB
MIN_EXTRACTED_TEXT_CHARS = 200
MAX_PARSED_TEXT_LENGTH = 200_000

# MAX_QUERY_LENGTH / SEARCH_TOP_K / SIMILARITY_THRESHOLD are deliberately absent: all
# three are environment configuration, injected into `SearchDocumentUseCase` from
# `Settings` by the composition root. Repeating them here as constants would shadow the
# settings outright and leave the `.env` values decorative.

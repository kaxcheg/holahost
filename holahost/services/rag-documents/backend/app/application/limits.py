"""Domain parameters the application layer needs (spec §3.7).

Plain constants, not yet sourced from typed settings — R-11 (Infrastructure, not yet
built) introduces real config loading. This matches the domain layer's own existing
precedent: `MAX_CHUNKS_PER_DOCUMENT` is already a bare module constant in
`domain.entities.document`, not injected. R-11 will replace these with real config
wherever they end up being consumed.
"""

from __future__ import annotations

MAX_UPLOAD_SIZE = 8 * 1024 * 1024  # 8 MiB
MIN_EXTRACTED_TEXT_CHARS = 200
MAX_PARSED_TEXT_LENGTH = 200_000
MAX_QUERY_LENGTH = 4000
SEARCH_TOP_K = 5
# Provisional — calibrated on real guidebooks later (spec, deferred decisions).
SIMILARITY_THRESHOLD = 0.30

"""Exceptions raised by this service's ports.

The three storage failures are the platform's — same types, same split by reaction, one
translation point from vendor errors — so they are re-exported from `holahost-db` rather
than redeclared. What is this service's own is the one below them.
"""

from __future__ import annotations

from holahost_db import ConcurrentUpdateError, IntegrityError, StorageUnavailableError

__all__ = [
    "ConcurrentUpdateError",
    "EmbeddingFailedError",
    "IntegrityError",
    "StorageUnavailableError",
]


class EmbeddingFailedError(Exception):
    """The embedding model failed to produce a vector for the given input."""

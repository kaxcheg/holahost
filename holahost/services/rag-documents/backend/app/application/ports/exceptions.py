"""Exceptions raised by storage-backed ports (repos, unit of work, vector search).

These are the port contract's own exception types (project convention, CLAUDE.md), not
vendor driver errors — infrastructure adapters translate driver-specific failures into
these three categories, chosen because calling code reacts to each differently.
"""

from __future__ import annotations


class StorageUnavailableError(Exception):
    """The database is unreachable, or a call to it timed out.

    Retrying inside the same request is pointless — callers should propagate this up
    rather than loop on it.
    """


class ConcurrentUpdateError(Exception):
    """A deadlock, serialization failure, or lock-wait timeout rolled back the transaction.

    The database rolled the transaction back, not application code — the caller may
    retry the whole transaction a bounded number of times (see UC-R2/UC-R5, §8.6).
    """


class IntegrityError(Exception):
    """A uniqueness, foreign-key, or check constraint was violated.

    A defect: entity invariants or a lock should have prevented the conflict before it
    reached storage. Not retried.
    """


class EmbeddingFailedError(Exception):
    """The embedding model failed to produce a vector for the given input."""

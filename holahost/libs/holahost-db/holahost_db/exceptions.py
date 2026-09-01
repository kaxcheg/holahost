"""The three ways storage fails, as the platform's port contract declares them.

Three types rather than one, and the split is by *reaction*, not by cause: the calling
code does something different with each. That is the whole test for whether a new type is
warranted, and it is why vendor driver errors never reach an application layer — they
carry a taxonomy nobody reacts to.
"""

from __future__ import annotations


class StorageUnavailableError(Exception):
    """The database is unreachable, or a call to it timed out.

    Retrying inside the same request is pointless — callers propagate this up rather than
    loop on it.
    """


class ConcurrentUpdateError(Exception):
    """A deadlock, serialization failure, or lock-wait timeout rolled back the transaction.

    The database rolled it back, not application code, so each retry starts from fresh
    state rather than repeating the same conflict — the caller may retry the whole
    transaction a bounded number of times.
    """


class IntegrityError(Exception):
    """A uniqueness, foreign-key, or check constraint was violated.

    A defect: entity invariants or a lock should have prevented the conflict before it
    reached storage. Not retried. Where a key conflict is a *normal* outcome — a redelivery,
    an idempotent insert — the implementation is expected to absorb it (``ON CONFLICT``)
    rather than let this reach the caller.
    """

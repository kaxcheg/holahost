"""Vendor driver errors -> the three-type storage contract.

One translation point for the whole platform: no repository, unit of work or script
re-implements this mapping, and nothing below the application layer lets a psycopg or
SQLAlchemy type escape upward.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg.errors
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from holahost_db.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    StorageUnavailableError,
)

# Class 40 (Transaction Rollback): the transaction is already gone, so retrying the whole
# `with uow:` block is the correct response. `QueryCanceled` covers a lock-wait timeout
# cancellation, which belongs in the same bucket for the same reason.
_CONCURRENCY_ERRORS: tuple[type[Exception], ...] = (
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
    psycopg.errors.QueryCanceled,
)
# Class 23 (Integrity Constraint Violation): entity invariants or a row lock should have
# prevented this — a defect, never retried. `InsufficientPrivilege` is here rather than
# with the failures because that is how a row-level-security `WITH CHECK` rejection
# surfaces: the statement was refused on the data it was about to write.
_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (
    psycopg.errors.UniqueViolation,
    psycopg.errors.ForeignKeyViolation,
    psycopg.errors.CheckViolation,
    psycopg.errors.InsufficientPrivilege,
)


@contextmanager
def translate_db_errors() -> Iterator[None]:
    """Wrap one database call, translating vendor errors to the three-type contract.

    Raises:
        ConcurrentUpdateError: serialization failure, deadlock, or a lock-wait
            statement-timeout cancellation — the caller may retry the whole transaction.
        IntegrityError: uniqueness/FK/check violation, or an RLS policy rejection — a
            defect; do not retry.
        StorageUnavailableError: connection lost, pool exhausted, a pool-internal
            connection-invalidation signal, or any other driver-level failure — retrying
            in-request is pointless.
    """
    try:
        yield
    except DBAPIError as e:
        # `DBAPIError` covers execution-time and connection-time driver failures alike,
        # but not everything SQLAlchemy raises — see below.
        orig = e.orig
        if isinstance(orig, _CONCURRENCY_ERRORS):
            raise ConcurrentUpdateError from e
        if isinstance(orig, _INTEGRITY_ERRORS):
            raise IntegrityError from e
        raise StorageUnavailableError from e
    except SQLAlchemyError as e:
        # The catch-all `DBAPIError` does not reach: a pool checkout timeout and a
        # connection-invalidation signal are direct `SQLAlchemyError` subclasses. None
        # carries an `.orig` to classify further; all mean "the storage layer failed".
        raise StorageUnavailableError from e

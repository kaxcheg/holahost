"""Translates vendor (psycopg/SQLAlchemy) driver errors into the three-type storage
error contract every port in `application/ports/` declares (CLAUDE.md port convention).
Single translation point — no repo/UoW method re-implements this mapping.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg.errors
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from application.ports.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    StorageUnavailableError,
)

# Class 40 (Transaction Rollback): the transaction is already gone by the time this is
# caught — retrying the whole `with uow:` block from scratch is the correct response.
# QueryCanceled also covers a lock-wait `statement_timeout` cancellation — CLAUDE.md's
# own project convention lists an "expired lock-wait timeout" explicitly as a
# ConcurrentUpdateError case.
_CONCURRENCY_ERRORS: tuple[type[Exception], ...] = (
    psycopg.errors.SerializationFailure,
    psycopg.errors.DeadlockDetected,
    psycopg.errors.QueryCanceled,
)
# Class 23 (Integrity Constraint Violation): the entity invariants or the row lock
# should have prevented this — a defect, never retried. InsufficientPrivilege also
# covers a Postgres RLS WITH CHECK failure on INSERT/UPDATE (§8.0) — reachable only
# if a caller's owner-consistency assert was somehow bypassed, so it belongs in the
# same "should have been prevented earlier" bucket as the other three.
_INTEGRITY_ERRORS: tuple[type[Exception], ...] = (
    psycopg.errors.UniqueViolation,
    psycopg.errors.ForeignKeyViolation,
    psycopg.errors.CheckViolation,
    psycopg.errors.InsufficientPrivilege,
)


@contextmanager
def translate_db_errors() -> Iterator[None]:
    """Wrap one DB call, translating vendor errors to the three-type contract.

    :raises ConcurrentUpdateError: serialization failure, deadlock, or a lock-wait
        statement-timeout cancellation — the caller may retry the whole transaction.
    :raises IntegrityError: uniqueness/FK/check violation, or an RLS policy
        rejection — a defect; do not retry.
    :raises StorageUnavailableError: connection lost, pool exhausted, a pool-internal
        connection-invalidation signal, or any other driver/SQLAlchemy-level failure —
        retrying in-request is pointless.
    """
    try:
        yield
    except DBAPIError as e:
        # DBAPIError covers execution-time AND connection-time driver failures alike
        # (verified empirically: a bad-port connect() raises OperationalError, itself
        # a DBAPIError subclass) — but NOT everything SQLAlchemy can raise; see below.
        orig = e.orig
        if isinstance(orig, _CONCURRENCY_ERRORS):
            raise ConcurrentUpdateError from e
        if isinstance(orig, _INTEGRITY_ERRORS):
            raise IntegrityError from e
        raise StorageUnavailableError from e
    except SQLAlchemyError as e:
        # Catch-all for everything DBAPIError does NOT cover: pool checkout timeout
        # (`exc.TimeoutError`) and pool-internal connection-invalidation signals
        # (`exc.DisconnectionError`/`InvalidatePoolError`) both live outside
        # DBAPIError's hierarchy — direct `SQLAlchemyError` subclasses instead
        # (verified: `issubclass(DisconnectionError, DBAPIError)` is False). None of
        # these carry a `.orig` to classify further; all mean "storage layer failed".
        raise StorageUnavailableError from e

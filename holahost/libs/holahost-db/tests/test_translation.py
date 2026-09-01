"""Driver errors reach an application layer as one of exactly three types.

Built from synthetic `DBAPIError`s rather than a live database: what is under test is the
classification, and the mapping from a psycopg error class to a reaction is the same
whether the connection was real.
"""

from __future__ import annotations

import psycopg.errors
import pytest
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from holahost_db import (
    ConcurrentUpdateError,
    IntegrityError,
    StorageUnavailableError,
    translate_db_errors,
)


def _dbapi_error(orig: Exception) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, orig)


class TestConcurrencyFailures:
    """Class 40 and its lock-wait sibling: the transaction is already gone, so the caller
    may re-run the whole thing."""

    @pytest.mark.parametrize(
        "orig",
        [
            psycopg.errors.SerializationFailure(),
            psycopg.errors.DeadlockDetected(),
            psycopg.errors.QueryCanceled(),
        ],
        ids=["serialization failure", "deadlock", "lock-wait timeout"],
    )
    def test_it_is_retryable(self, orig: Exception) -> None:
        with pytest.raises(ConcurrentUpdateError), translate_db_errors():
            raise _dbapi_error(orig)

    def test_a_lock_wait_timeout_is_not_reported_as_unavailable(self) -> None:
        # `QueryCanceled` is what `lock_timeout` produces, and reading it as "the database
        # is down" would turn an ordinary contended write into a 500 instead of a retry.
        with pytest.raises(ConcurrentUpdateError), translate_db_errors():
            raise _dbapi_error(psycopg.errors.QueryCanceled())


class TestIntegrityFailures:
    """Class 23 and the RLS rejection: a defect, never retried."""

    @pytest.mark.parametrize(
        "orig",
        [
            psycopg.errors.UniqueViolation(),
            psycopg.errors.ForeignKeyViolation(),
            psycopg.errors.CheckViolation(),
        ],
        ids=["unique", "foreign key", "check"],
    )
    def test_a_constraint_violation_is_a_defect(self, orig: Exception) -> None:
        with pytest.raises(IntegrityError), translate_db_errors():
            raise _dbapi_error(orig)

    def test_an_rls_rejection_is_a_defect_too(self) -> None:
        # A `WITH CHECK` rejection surfaces as InsufficientPrivilege. It belongs with the
        # constraint violations: the row the statement was about to write was refused, and
        # retrying writes the same row again.
        with pytest.raises(IntegrityError), translate_db_errors():
            raise _dbapi_error(psycopg.errors.InsufficientPrivilege())


class TestUnavailability:
    def test_an_unclassified_driver_error_is_unavailable(self) -> None:
        with pytest.raises(StorageUnavailableError), translate_db_errors():
            raise _dbapi_error(psycopg.errors.OperationalError())

    @pytest.mark.parametrize(
        "error",
        [SATimeoutError("pool checkout timed out"), InvalidRequestError("connection invalidated")],
        ids=["pool checkout timeout", "connection invalidated"],
    )
    def test_a_sqlalchemy_error_without_an_orig_is_unavailable(self, error: Exception) -> None:
        # These never reach the `DBAPIError` branch: they are direct `SQLAlchemyError`
        # subclasses with no `.orig` to classify. Without the second `except` they would
        # escape as vendor types into an application layer that declares three.
        with pytest.raises(StorageUnavailableError), translate_db_errors():
            raise error


def test_a_clean_block_passes_through() -> None:
    with translate_db_errors():
        pass


def test_an_unrelated_exception_is_left_alone() -> None:
    # Only storage failures are this module's business — swallowing anything else into
    # `StorageUnavailableError` would hide a defect as an outage.
    with pytest.raises(ValueError), translate_db_errors():
        raise ValueError("not a storage failure")

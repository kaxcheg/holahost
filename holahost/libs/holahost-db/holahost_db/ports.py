"""The transactional boundary, as an application layer declares it.

Kept free of any storage import on purpose: a service's application layer depends on this
Protocol, and depending on it must not put SQLAlchemy within reach of that layer. The
package's import contract enforces it.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol


class UnitOfWork(Protocol):
    """Demarcates one atomic transaction."""

    def __enter__(self) -> UnitOfWork:
        """Begin the transaction."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit on clean exit; roll back and re-raise on exception.

        Concurrency: hold any lock taken inside until commit/rollback, not before.
        """
        ...

    def commit(self) -> None:
        """Commit the transaction explicitly.

        Raises:
            StorageUnavailableError: the database is unreachable or timed out.
            ConcurrentUpdateError: deadlock, serialization failure, or a lock-wait
                timeout — the transaction was rolled back by the database.
            IntegrityError: a stored invariant was violated (internal defect).
        """
        ...

    def rollback(self) -> None:
        """Roll back the transaction explicitly."""
        ...

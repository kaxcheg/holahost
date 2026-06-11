from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class UnitOfWork(Protocol):
    """Port: transactional boundary for write operations (spec §8.2.9)."""

    def transaction(self) -> AbstractContextManager[None]:
        """Return a context manager that commits on success and rolls back on exception.

        Use cases wrap write phases in ``with uow.transaction(): ...`` (§9). Repo impls bind
        to the UoW's current connection/transaction.
        """
        ...

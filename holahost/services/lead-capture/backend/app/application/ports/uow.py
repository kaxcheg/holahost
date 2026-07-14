from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class UnitOfWork(Protocol):
    """Port: transactional boundary for write operations (spec §8.2.9)."""

    def transaction(self) -> AbstractContextManager[None]:
        """Return a context manager that commits on success and rolls back on exception.

        Use cases wrap write phases in ``with uow.transaction(): ...`` (§9). Repo impls bind
        to the UoW's current connection/transaction. Baseline isolation is READ COMMITTED (§9.0).
        This boundary provides **atomicity** (all-or-nothing commit) only — it does NOT provide
        **race-protection** (the two are distinct). Guarding concurrent transactions from
        interfering is pushed to the adapters via the per-port race-protection contracts
        (``RateLimiter`` / ``SampleBudgetRepo`` / ``LeadsRepo``): conditional statements / row locks.
        """
        ...

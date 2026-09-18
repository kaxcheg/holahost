"""Port for the usage log."""

from __future__ import annotations

from typing import Protocol

from domain.entities.usage_record import UsageRecord


class UsageRepo(Protocol):
    """Appends to the usage log — the source of every budget and the record of what was spent."""

    def add(self, record: UsageRecord) -> None:
        """Append `record`.

        Idempotent by `record.id`: inserting the same record again is absorbed rather than raised,
        so a transaction retried after a conflict neither duplicates the record nor fails on it. No
        lock: the log is only ever appended to. Call inside an open unit of work.

        :param record: The record to append.
        :raises StorageUnavailableError: the database is unreachable or timed out.
        :raises ConcurrentUpdateError: the statement was cancelled or the transaction rolled back —
            the whole transaction may be retried.
        :raises IntegrityError: a stored constraint rejected the record — a defect, not retried.
        """
        ...

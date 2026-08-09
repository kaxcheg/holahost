"""Shared retry loop for the "retried up to twice on a concurrency conflict"
contract UC-R2 (replace) and UC-R5 (delete) both need (spec §8.6)."""

from __future__ import annotations

from collections.abc import Callable

from application.ports.exceptions import ConcurrentUpdateError


def retry_on_concurrent_update[T](fn: Callable[[], T], *, max_retries: int = 2) -> T:
    """Call ``fn``, retrying it whole on ``ConcurrentUpdateError``, up to ``max_retries`` times.

    Per §8.6, a replace/delete transaction that loses a concurrency conflict is
    retried in full, but no more than twice — up to 3 attempts total. The database has
    already rolled back the losing transaction by the time this catches the exception,
    so each retry starts from fresh state, not a repeat of the same conflict.

    Args:
        fn: A zero-argument callable performing one attempt (typically a locked
            read-modify-write wrapped in ``with uow: ...``).
        max_retries: Maximum number of retries after the initial attempt.

    Returns:
        Whatever ``fn`` returns, from whichever attempt succeeded.

    Raises:
        ConcurrentUpdateError: every attempt (initial + ``max_retries`` retries) failed.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except ConcurrentUpdateError:
            attempt += 1
            if attempt > max_retries:
                raise

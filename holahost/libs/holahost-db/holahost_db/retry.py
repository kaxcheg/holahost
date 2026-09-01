"""Retrying a transaction the database rolled back under a concurrency conflict."""

from __future__ import annotations

from collections.abc import Callable

from holahost_db.exceptions import ConcurrentUpdateError

DEFAULT_MAX_RETRIES = 2
"""Three attempts in all. A conflict on the same row is a real and recoverable event, so
answering the first one with a 500 is wrong; but a caller that keeps losing is contending
with something that is not going away inside one request."""


def retry_on_concurrent_update[T](
    fn: Callable[[], T], *, max_retries: int = DEFAULT_MAX_RETRIES
) -> T:
    """Call ``fn``, retrying it whole on ``ConcurrentUpdateError``.

    The database has already rolled the losing transaction back by the time this catches
    the exception, so each retry starts from fresh state rather than repeating the same
    conflict. Whole, not partial: whatever ``fn`` read before the conflict is gone with the
    transaction, so resuming inside it would work from a snapshot that no longer exists.

    Args:
        fn: A zero-argument callable performing one attempt — typically a locked
            read-modify-write wrapped in ``with uow: ...``. Anything expensive and
            side-effect-free (a parse, an embedding, a remote call) belongs *outside* it,
            so a retry does not pay for it again.
        max_retries: Retries after the initial attempt.

    Returns:
        Whatever ``fn`` returns, from whichever attempt succeeded.

    Raises:
        ConcurrentUpdateError: every attempt failed.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except ConcurrentUpdateError:
            attempt += 1
            if attempt > max_retries:
                raise

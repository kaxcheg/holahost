"""Wraps a bare ``ValueError`` — the domain/application VO convention for signaling
an internal defect, not client-fixable input (see ``domain/exceptions.py``) — into
``ApplicationError`` at the use-case boundary.

Without this, a bare ``ValueError`` propagates as a stdlib type shared across the
whole Python ecosystem (Pydantic, ``int()``/``float()`` parsing, etc.), risking
accidental capture by an unrelated ``except ValueError`` written for a different
purpose elsewhere in the call stack, and forcing the interface layer to handle two
exception families instead of one.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from application.exceptions import ApplicationError


def wrap_value_error[**P, T](fn: Callable[P, T]) -> Callable[P, T]:
    """Catch a bare ``ValueError`` raised by ``fn`` and re-raise as
    ``ApplicationError`` (default ``code=ERR_INTERNAL``), chained via ``from e``.

    Only ``ValueError`` — not a broad ``except Exception`` — so it doesn't also
    swallow the port-level exceptions (``StorageUnavailableError``,
    ``ConcurrentUpdateError``, ``IntegrityError``, ``EmbeddingFailedError``,
    ``RateLimitExceededError``), which are documented "conscious pass-through" and
    must keep their own type identity.
    """

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return fn(*args, **kwargs)
        except ValueError as e:
            raise ApplicationError(str(e)) from e

    return wrapper

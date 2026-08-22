from __future__ import annotations

import pytest
from tests._support.db import build_test_uow

from application.ports.exceptions import StorageUnavailableError


class TestTranslateDbErrors:
    def test_connection_failure_translates_to_storage_unavailable(self) -> None:
        """A connect()-time failure (not a statement-execution failure) must still be
        translated — DBAPIError covers both (verified: OperationalError from a bad
        connect() is itself a DBAPIError subclass), so this is a regression guard, not
        just a new-behavior check.
        """
        # Port 1 is a safe bet for "closed, connection refused" in any sandboxed env. The DSN
        # spells its driver dialect out, same as every real one here (`config.settings`
        # builds them that way): a bare `postgresql://` resolves to SQLAlchemy's *default*
        # postgres dialect, psycopg2, which this project does not depend on.
        uow = build_test_uow("postgresql+psycopg://user:pass@localhost:1/nonexistent")
        with pytest.raises(StorageUnavailableError), uow:
            pass

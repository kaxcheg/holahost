from __future__ import annotations

import pytest

from application.ports.exceptions import StorageUnavailableError
from infrastructure.db.sqlalchemy_unit_of_work import SqlAlchemyUnitOfWork


class TestTranslateDbErrors:
    def test_connection_failure_translates_to_storage_unavailable(self) -> None:
        """A connect()-time failure (not a statement-execution failure) must still be
        translated — DBAPIError covers both (verified: OperationalError from a bad
        connect() is itself a DBAPIError subclass), so this is a regression guard, not
        just a new-behavior check.
        """
        # Port 1 is a safe bet for "closed, connection refused" in any sandboxed env.
        uow = SqlAlchemyUnitOfWork("postgresql://user:pass@localhost:1/nonexistent")
        with pytest.raises(StorageUnavailableError), uow:
            pass

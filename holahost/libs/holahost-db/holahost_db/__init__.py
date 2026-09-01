"""holahost-db: the Postgres access layer every Holahost service shares."""

from holahost_db.exceptions import (
    ConcurrentUpdateError,
    IntegrityError,
    StorageUnavailableError,
)
from holahost_db.ports import UnitOfWork
from holahost_db.provisioning import provision_app_role
from holahost_db.retry import DEFAULT_MAX_RETRIES, retry_on_concurrent_update
from holahost_db.rls import DEFAULT_OWNER_SETTING, assert_rls_is_enforced, bind_rls_owner
from holahost_db.settings import (
    AppRoleSettings,
    PostgresLocation,
    SuperuserSettings,
    postgres_dsn,
)
from holahost_db.translation import translate_db_errors
from holahost_db.uow import (
    DEFAULT_LOCK_TIMEOUT_MS,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    SqlAlchemyUnitOfWork,
    build_engine,
)

__all__ = [
    "DEFAULT_LOCK_TIMEOUT_MS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_OWNER_SETTING",
    "DEFAULT_STATEMENT_TIMEOUT_MS",
    "AppRoleSettings",
    "ConcurrentUpdateError",
    "IntegrityError",
    "PostgresLocation",
    "SqlAlchemyUnitOfWork",
    "StorageUnavailableError",
    "SuperuserSettings",
    "UnitOfWork",
    "assert_rls_is_enforced",
    "bind_rls_owner",
    "build_engine",
    "postgres_dsn",
    "provision_app_role",
    "retry_on_concurrent_update",
    "translate_db_errors",
]

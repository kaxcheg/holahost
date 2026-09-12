# holahost-db

The Postgres access layer shared by Holahost services: the storage error contract, the
unit of work, the two identities a service connects with, and the deploy-time provisioning
that keeps them apart.

Consumed as a [path dependency](../../README.md#shared-libraries).

## Why a library and not a copy per service

Not for the line count. Every piece here is something that goes wrong in a way nothing
reports until it matters:

- **The classification.** `QueryCanceled` is a *concurrency* failure, because a lock-wait
  timeout is one and its transaction is already rolled back. `InsufficientPrivilege` is an
  *integrity* failure, because that is how a row-level-security `WITH CHECK` rejection
  surfaces. A bare `SQLAlchemyError` with no `.orig` is *unavailable*, because a pool
  checkout timeout and a connection-invalidation signal arrive that way. Get any of the
  three wrong and a retryable failure becomes a 500, or a defect gets retried.
- **The password.** A DSN built by interpolation breaks on a generated password containing
  `@`; a role password composed with SQLAlchemy's literal processor doubles a `%` and
  locks the service out of its own database on the next connect. Both are silent until a
  rotation produces the wrong character.
- **The two identities.** Isolation by row-level security is worth exactly nothing if the
  application connects as a role that bypasses it, and nothing in a passing test suite
  says so.

## What it provides

| Piece | What it does |
|---|---|
| `StorageUnavailableError`, `ConcurrentUpdateError`, `IntegrityError` | The three ways storage fails, split by what the caller does about each. |
| `UnitOfWork` | The transaction boundary an application layer declares. |
| `translate_db_errors` | Driver errors -> the three above. One translation point. |
| `build_engine` | The process-shared engine: pool, pre-ping, UTC, statement and lock timeouts, an `on_connect` hook for per-connection codecs. |
| `SqlAlchemyUnitOfWork` | One in-flight transaction on that engine, fresh per request. |
| `retry_on_concurrent_update` | Re-runs a whole transaction the database rolled back. |
| `PostgresLocation`, `AppRoleSettings`, `SuperuserSettings`, `postgres_dsn` | The two identities, and correct DSN assembly. |
| `bind_rls_owner`, `assert_rls_is_enforced` | Row-level security: scope a transaction, and refuse to serve without it. |
| `provision_app_role` | Create/re-assert the unprivileged role, its password and its grants. |
| `alembic_support.run_migrations` | Everything a service's `migrations/env.py` does but naming its `MetaData`. |

## What it does not provide

**Repositories, schema, or a base class for either.** An owner-bound adapter is three lines
of `bind_rls_owner` and a connection accessor; a base class over it would have to fix the
*set of methods* a repository has, which is the one thing that is genuinely per-service.

**The row-level-security policy.** A migration's SQL is history — it records what was
applied — so a helper that changed later would change the meaning of migrations already
run. Write it out in the migration, next to the table it protects:

```sql
ALTER TABLE things ENABLE ROW LEVEL SECURITY;
ALTER TABLE things FORCE ROW LEVEL SECURITY;   -- ENABLE alone does not apply to the owner
CREATE POLICY owner_isolation ON things
    USING      (owner_subject = current_setting('app.current_owner', true))
    WITH CHECK (owner_subject = current_setting('app.current_owner', true));
```

A child table derives visibility through its parent rather than carrying its own owner
column, so the parent's policy is the only place the rule is stated:

```sql
CREATE POLICY owner_isolation ON parts
    USING      (thing_id IN (SELECT id FROM things))
    WITH CHECK (thing_id IN (SELECT id FROM things));
```

`FORCE` matters: without it the policies do not apply to the role that owns the table. And
no `FORCE` closes the superuser hole — a superuser bypasses row-level security
unconditionally, which is what `assert_rls_is_enforced` is for.

**Row-level security at all, for a service that has no subject to isolate.** A ledger read
by an operator and aggregated by client needs neither `bind_rls_owner` nor the setting.

## The two identities

| | Creates the schema | Serves traffic |
|---|---|---|
| Model | `SuperuserSettings` | `AppRoleSettings` |
| Who | the database container's initdb superuser | the role `provision_app_role` creates |
| Used by | `migrations/env.py`, `provision_app_role` | the application process |
| Privileges | owns the tables, may create extensions and policies | `LOGIN NOSUPERUSER NOBYPASSRLS`, DML on `public`, no ownership |

Deploy order is fixed and each step depends on the one before: `alembic upgrade head`
creates the tables as their owner, then `provision_app_role` grants the app role DML on
whatever now exists, then the container swaps. Provisioning runs *every* deploy, not once:
it is also what applies a rotated password, since the Postgres image sets one at initdb and
never again.

## Wiring `migrations/env.py`

```python
from holahost_db.alembic_support import run_migrations

from infrastructure.db.schema import metadata

run_migrations(metadata)
```

That is the whole file. `alembic_support` is not re-exported from the package root on
purpose: it imports `alembic.context`, which exists only while a migration run is in
progress.

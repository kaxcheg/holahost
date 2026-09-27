"""`UsageRepo` over Postgres: the usage log, appended to and never changed."""

from __future__ import annotations

from holahost_db import SqlAlchemyUnitOfWork, translate_db_errors
from sqlalchemy.dialects.postgresql import insert

from domain.entities.usage_record import UsageRecord
from infrastructure.db.schema import usage_records


class SqlAlchemyUsageRepo:
    """Appends through the request's unit of work. No lock: nothing ever competes for a row."""

    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def add(self, record: UsageRecord) -> None:
        # `ON CONFLICT DO NOTHING` on the identifier: a transaction retried after a conflict inserts
        # the same record again, and that is redelivery rather than a defect.
        statement = (
            insert(usage_records)
            .values(
                id=record.id,
                request_id=record.request_id,
                client_id=record.client_id.value,
                subject=record.subject.value,
                provider=record.provider.value,
                model=record.model.value,
                input_tokens=record.usage.input_tokens.value,
                output_tokens=record.usage.output_tokens.value,
                latency_ms=record.latency_ms,
                downgraded=record.downgraded,
                failed_over=record.failed_over,
                created_at=record.created_at,
            )
            .on_conflict_do_nothing(index_elements=[usage_records.c.id])
        )
        with translate_db_errors():
            self._uow.connection().execute(statement)

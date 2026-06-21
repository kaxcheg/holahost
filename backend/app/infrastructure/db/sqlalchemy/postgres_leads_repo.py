from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr
from sqlalchemy import RowMapping, Select, insert, select, update
from sqlalchemy.exc import IntegrityError

from application.exceptions import EmailConflictError
from domain.entities.lead import Lead
from domain.value_objects.email import Email
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.ip_hash import IpHash
from domain.value_objects.lead_flow import LeadFlow
from domain.value_objects.lead_id import LeadId
from domain.value_objects.magic_link import MagicLink
from infrastructure.db.sqlalchemy import schema
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork


def _to_values(lead: Lead) -> dict[str, Any]:
    """Map a ``Lead`` to its column→value dict (value-objects unwrapped to primitives here only)."""
    return {
        "id": lead.id,
        "email": lead.email.value,
        "magic_link": None if lead.magic_link is None else lead.magic_link.value.get_secret_value(),
        "captured_at": lead.captured_at,
        "last_seen_at": lead.last_seen_at,
        "flow": lead.flow.value,
        "guidebook_id": lead.guidebook_id,
        "ip_hash": lead.ip_hash.value,
        "ua_short": lead.ua_short,
    }


def _from_row(row: RowMapping) -> Lead:
    magic_link = row["magic_link"]
    guidebook_id = row["guidebook_id"]
    return Lead.from_repo(
        id=LeadId(bytes=row["id"].bytes),
        email=Email(row["email"]),
        magic_link=None if magic_link is None else MagicLink(SecretStr(magic_link)),
        captured_at=row["captured_at"],
        last_seen_at=row["last_seen_at"],
        flow=LeadFlow(row["flow"]),
        guidebook_id=None if guidebook_id is None else GuidebookId(bytes=guidebook_id.bytes),
        ip_hash=IpHash(row["ip_hash"]),
        ua_short=row["ua_short"],
    )


class PostgresLeadsRepo:
    """Postgres adapter for the ``LeadsRepo`` port (spec §4.1); runs on ``uow.connection``."""

    def __init__(self, uow: PostgresUnitOfWork) -> None:
        self._uow = uow

    def get_by_id_for_update(self, id: LeadId) -> Lead | None:
        return self._fetch(select(schema.leads).where(schema.leads.c.id == id).with_for_update())

    def get_by_email_for_update(self, email: Email) -> Lead | None:
        return self._fetch(
            select(schema.leads).where(schema.leads.c.email == email.value).with_for_update()
        )

    def get_by_magic_link(self, magic_link: MagicLink) -> Lead | None:
        return self._fetch(
            select(schema.leads).where(
                schema.leads.c.magic_link == magic_link.value.get_secret_value()
            )
        )

    def get_by_magic_link_for_update(self, magic_link: MagicLink) -> Lead | None:
        return self._fetch(
            select(schema.leads)
            .where(schema.leads.c.magic_link == magic_link.value.get_secret_value())
            .with_for_update()
        )

    def add(self, lead: Lead) -> None:
        try:
            self._uow.connection.execute(insert(schema.leads).values(_to_values(lead)))
        except IntegrityError as e:
            # Lost the UNIQUE(email) race (§4.1, C-08) — the only unique constraint on this path.
            # Propagates out of uow.transaction() → ROLLBACK; the caller retries via the upsert path.
            raise EmailConflictError(lead.email.value) from e

    def update(self, lead: Lead) -> None:
        # Full-row write of the lead's current state (§9.0 / C-12 p.4); safe because the caller holds
        # the row lock from a *_for_update read. The PK is the WHERE key, not a SET target.
        values = _to_values(lead)
        del values["id"]
        self._uow.connection.execute(
            update(schema.leads).where(schema.leads.c.id == lead.id).values(values)
        )

    def list_expired(self, threshold: datetime, limit: int) -> list[Lead]:
        rows = (
            self._uow.connection.execute(
                select(schema.leads)
                .where(
                    schema.leads.c.magic_link.isnot(None),
                    schema.leads.c.last_seen_at < threshold,
                )
                .order_by(schema.leads.c.last_seen_at)
                .limit(limit)
            )
            .mappings()
            .all()
        )
        return [_from_row(row) for row in rows]

    def _fetch(self, stmt: Select[Any]) -> Lead | None:
        # one_or_none(): every caller looks up by a unique key (PK id / unique email / unique
        # magic_link), so >1 row is a data-integrity violation worth surfacing, not silently taking
        # the first.
        row = self._uow.connection.execute(stmt).mappings().one_or_none()
        return None if row is None else _from_row(row)


if TYPE_CHECKING:
    from application.ports.repos import LeadsRepo

    # Structural port conformance (the class deliberately does NOT inherit the Protocol).
    def _conforms(x: PostgresLeadsRepo) -> LeadsRepo:
        return x

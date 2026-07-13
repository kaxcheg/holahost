from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from application.exceptions import EmailConflictError
from domain.entities.lead import Lead
from domain.value_objects.email import Email
from domain.value_objects.ip_hash import IpHash
from domain.value_objects.lead_flow import LeadFlow
from domain.value_objects.magic_link import MagicLink
from infrastructure.db.sqlalchemy.postgres_leads_repo import PostgresLeadsRepo
from infrastructure.db.sqlalchemy.postgres_uow import PostgresUnitOfWork

_IP = "0" * 64


def _make(email: str, token: str) -> Lead:
    return Lead.create(
        email=Email(email),
        magic_link=MagicLink(SecretStr(token)),
        flow=LeadFlow.SAMPLE,
        ip_hash=IpHash(_IP),
        ua_short=None,
    )


@pytest.mark.integration
def test_get_by_id_and_magic_link_for_update_round_trip(uow: PostgresUnitOfWork) -> None:
    lead = _make("fu@example.com", "tok-fu")
    repo = PostgresLeadsRepo(uow)
    with uow.transaction():
        repo.add(lead)
    with uow.transaction():  # exercises both *_for_update WHERE-column paths (id, magic_link)
        by_id = repo.get_by_id_for_update(lead.id)
        by_ml = repo.get_by_magic_link_for_update(MagicLink(SecretStr("tok-fu")))
    assert by_id is not None
    assert by_id.id == lead.id
    assert by_ml is not None
    assert by_ml.id == lead.id


@pytest.mark.integration
def test_add_then_get_by_email_round_trips(uow: PostgresUnitOfWork) -> None:
    lead = _make("a@example.com", "tok-a")
    with uow.transaction():
        PostgresLeadsRepo(uow).add(lead)
    with uow.transaction():
        loaded = PostgresLeadsRepo(uow).get_by_email_for_update(Email("a@example.com"))
    assert loaded is not None
    assert loaded.id == lead.id
    assert loaded.last_seen_at == lead.last_seen_at
    assert loaded.flow is LeadFlow.SAMPLE
    assert loaded.magic_link is not None
    assert loaded.magic_link.value.get_secret_value() == "tok-a"


@pytest.mark.integration
def test_update_persists_regenerated_magic_link(uow: PostgresUnitOfWork) -> None:
    lead = _make("b@example.com", "tok-b1")
    repo = PostgresLeadsRepo(uow)
    with uow.transaction():
        repo.add(lead)
    lead.regenerate_magic_link(MagicLink(SecretStr("tok-b2")))
    with uow.transaction():
        repo.update(lead)
    with uow.transaction():
        loaded = repo.get_by_magic_link(MagicLink(SecretStr("tok-b2")))
    assert loaded is not None
    assert loaded.id == lead.id


@pytest.mark.integration
def test_list_expired_returns_only_stale_with_magic_link(uow: PostgresUnitOfWork) -> None:
    fresh = _make("fresh@example.com", "tok-f")
    stale = _make("stale@example.com", "tok-s")
    stale.last_seen_at = datetime.now(tz=UTC) - timedelta(days=40)
    repo = PostgresLeadsRepo(uow)
    with uow.transaction():
        repo.add(fresh)
        repo.add(stale)
    threshold = datetime.now(tz=UTC) - timedelta(days=30)
    with uow.transaction():
        expired = repo.list_expired(threshold, limit=10)
    assert [item.email.value for item in expired] == ["stale@example.com"]


@pytest.mark.integration
def test_add_duplicate_email_raises_email_conflict(uow: PostgresUnitOfWork) -> None:
    repo = PostgresLeadsRepo(uow)
    with uow.transaction():
        repo.add(_make("dup@example.com", "tok-1"))
    # pytest.raises is the OUTER cm so the inner uow.transaction() exits first → ROLLBACK on the
    # re-raised EmailConflictError (conn aborted by UniqueViolation), then pytest.raises catches it.
    with pytest.raises(EmailConflictError), uow.transaction():
        repo.add(_make("dup@example.com", "tok-2"))
    with uow.transaction():
        rows = uow.connection.execute(
            text("SELECT id FROM leads WHERE email = :email"), {"email": "dup@example.com"}
        ).fetchall()
    assert len(rows) == 1  # loser rolled back; connection usable afterwards

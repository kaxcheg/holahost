from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from domain.value_objects.email import Email
from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.ip_hash import IpHash
from domain.value_objects.lead_flow import LeadFlow
from domain.value_objects.lead_id import LeadId
from domain.value_objects.magic_link import MagicLink


@dataclass(eq=False)
class Lead:
    """Persistent lead entity (spec §7.5).

    Central funnel entity tying together email, magic-link token, optional
    guidebook attachment, and capture-flow context. Identified by its
    system-generated ``id``; equality and hashing are by ``id``
    (spec §7.0 — persistent-entity identity): ``eq=False`` disables dataclass
    field-wise equality so the explicit ``__eq__``/``__hash__`` govern.

    Args:
        id: System-generated identifier.
        email: Validated email address.
        magic_link: URL-safe opaque token delivered via email; ``None`` after
            ``expire_magic_link()`` (cleanup TTL exhaustion, spec §4.7).
        captured_at: Timestamp when the lead was first created (timezone-aware UTC).
        last_seen_at: Timestamp of the most recent activity (timezone-aware UTC).
        flow: Capture context — ``GUIDEBOOK`` or ``SAMPLE``.
        guidebook_id: FK to the attached guidebook, or ``None`` if none uploaded yet.
        ip_hash: SHA-256 hash of the creator's IP (spec §10.5).
        ua_short: Truncated user-agent string, or ``None``.
    """

    id: LeadId
    email: Email
    magic_link: MagicLink | None
    captured_at: datetime
    last_seen_at: datetime
    flow: LeadFlow
    guidebook_id: GuidebookId | None
    ip_hash: IpHash
    ua_short: str | None

    @classmethod
    def create(
        cls,
        email: Email,
        magic_link: MagicLink,
        flow: LeadFlow,
        ip_hash: IpHash,
        ua_short: str | None,
    ) -> Lead:
        """Create a new lead with a fresh id and both timestamps set to now (UTC).

        ``guidebook_id`` is always ``None`` at creation; attached later via
        ``attach_guidebook()`` once the host uploads a guidebook (spec §7.5).

        Args:
            email: Validated email address.
            magic_link: Freshly generated magic-link token.
            flow: Capture context (``GUIDEBOOK`` or ``SAMPLE``).
            ip_hash: Hash of the creator's IP.
            ua_short: Truncated user-agent string, or ``None``.

        Returns:
            A new ``Lead`` with a generated ``id``.
        """
        now = datetime.now(tz=UTC)
        return cls(
            id=LeadId.new(),
            email=email,
            magic_link=magic_link,
            captured_at=now,
            last_seen_at=now,
            flow=flow,
            guidebook_id=None,
            ip_hash=ip_hash,
            ua_short=ua_short,
        )

    @classmethod
    def from_repo(
        cls,
        id: LeadId,
        email: Email,
        magic_link: MagicLink | None,
        captured_at: datetime,
        last_seen_at: datetime,
        flow: LeadFlow,
        guidebook_id: GuidebookId | None,
        ip_hash: IpHash,
        ua_short: str | None,
    ) -> Lead:
        """Reconstruct a lead from persisted values (no id generation).

        Args:
            id: Persisted identifier.
            email: Persisted email.
            magic_link: Persisted token, or ``None`` if expired.
            captured_at: Persisted creation timestamp.
            last_seen_at: Persisted last-activity timestamp.
            flow: Persisted capture context.
            guidebook_id: Persisted guidebook FK, or ``None``.
            ip_hash: Persisted IP hash.
            ua_short: Persisted user-agent, or ``None``.

        Returns:
            The reconstructed ``Lead``.
        """
        return cls(
            id=id,
            email=email,
            magic_link=magic_link,
            captured_at=captured_at,
            last_seen_at=last_seen_at,
            flow=flow,
            guidebook_id=guidebook_id,
            ip_hash=ip_hash,
            ua_short=ua_short,
        )

    def regenerate_magic_link(self, new_magic_link: MagicLink) -> None:
        """Replace the magic-link token and advance ``last_seen_at``.

        Called by ``CaptureLeadUseCase`` on silent upsert (existing email resubmits,
        spec §7.5). ``flow`` is NOT updated — it is fixed at first capture.

        Args:
            new_magic_link: Freshly generated replacement token.
        """
        self.magic_link = new_magic_link
        self.last_seen_at = datetime.now(tz=UTC)

    def attach_guidebook(self, guidebook_id: GuidebookId) -> None:
        """Attach a guidebook to this lead and advance ``last_seen_at``.

        Called by ``UploadGuidebookUseCase`` after a guidebook is persisted.
        On replace, the repo deletes the old guidebook (CASCADE chunks) and this
        method switches the FK to the new id (spec §7.5).

        Args:
            guidebook_id: Id of the newly persisted guidebook.
        """
        self.guidebook_id = guidebook_id
        self.last_seen_at = datetime.now(tz=UTC)

    def detach_guidebook(self) -> None:
        """Clear the guidebook FK without advancing ``last_seen_at``.

        Called by ``CleanupExpiredUseCase`` after deleting an expired guidebook.
        DB-side ``ON DELETE SET NULL`` already cleared the column; this call
        synchronises domain state so a subsequent ``repo.update(lead)`` does not
        overwrite the DB ``NULL`` with the stale id (spec §7.5).
        """
        self.guidebook_id = None

    def touch(self) -> None:
        """Advance ``last_seen_at`` to now (UTC).

        Implements the sliding-TTL signal gamma (spec §10.1): called on magic-link
        resolve, guidebook upload, and generate-response.
        """
        self.last_seen_at = datetime.now(tz=UTC)

    def expire_magic_link(self) -> None:
        """Set ``magic_link`` to ``None`` — called by cleanup after TTL expiry.

        The lead row is retained for analytics; only the token is cleared (spec §4.7).
        """
        self.magic_link = None

    def __eq__(self, other: object) -> bool:
        """Equality by ``id`` (persistent-entity identity, spec §7.0)."""
        if not isinstance(other, Lead):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash by ``id`` (stable under mutation)."""
        return hash(self.id)

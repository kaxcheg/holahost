from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from domain.value_objects.guidebook_id import GuidebookId
from domain.value_objects.guidebook_name import GuidebookName
from domain.value_objects.ip_hash import IpHash


@dataclass(eq=False)
class Guidebook:
    """Persistent guidebook entity (spec §7.3).

    Identified by its system-generated ``id`` (assigned in ``create()``, round-tripped via
    ``from_repo()``). Equality and hashing are **by ``id``** (spec §7.0 — persistent-entity
    identity): ``eq=False`` disables dataclass field-wise equality so the explicit
    ``__eq__``/``__hash__`` below govern, keeping identity stable across ``touch()`` mutation and
    instances hashable.

    Args:
        id: System-generated identifier.
        name: Display name (``GuidebookName`` VO; non-empty, max 100 — D5/D6).
        created_at: Creation timestamp (timezone-aware UTC).
        last_accessed_at: Last-access timestamp (timezone-aware UTC); advanced by ``touch()``.
        ip_hash: Hash of the creator's IP.
    """

    id: GuidebookId
    name: GuidebookName
    created_at: datetime
    last_accessed_at: datetime
    ip_hash: IpHash

    @classmethod
    def create(cls, name: GuidebookName, ip_hash: IpHash) -> Guidebook:
        """Create a new guidebook with a fresh id and both timestamps set to now (UTC).

        Args:
            name: Display name.
            ip_hash: Hash of the creator's IP.

        Returns:
            A new ``Guidebook`` with a generated ``id``.
        """
        now = datetime.now(tz=UTC)
        return cls(
            id=GuidebookId.new(),
            name=name,
            created_at=now,
            last_accessed_at=now,
            ip_hash=ip_hash,
        )

    @classmethod
    def from_repo(
        cls,
        id: GuidebookId,
        name: GuidebookName,
        created_at: datetime,
        last_accessed_at: datetime,
        ip_hash: IpHash,
    ) -> Guidebook:
        """Reconstruct a guidebook from persisted values (no id generation).

        Args:
            id: Persisted identifier.
            name: Persisted display name.
            created_at: Persisted creation timestamp.
            last_accessed_at: Persisted last-access timestamp.
            ip_hash: Persisted IP hash.

        Returns:
            The reconstructed ``Guidebook``.
        """
        return cls(
            id=id,
            name=name,
            created_at=created_at,
            last_accessed_at=last_accessed_at,
            ip_hash=ip_hash,
        )

    def touch(self) -> None:
        """Advance ``last_accessed_at`` to now (UTC) — on successful ``/api/capture-lead/generate`` (§6.5)."""
        self.last_accessed_at = datetime.now(tz=UTC)

    def __eq__(self, other: object) -> bool:
        """Equality by ``id`` (persistent-entity identity, spec §7.0)."""
        if not isinstance(other, Guidebook):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash by ``id`` (stable under mutation)."""
        return hash(self.id)

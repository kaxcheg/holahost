from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr


@dataclass(frozen=True)
class UploadGuidebookCmd:
    """Command for POST /api/lead-capture/ingest/upload (spec §8.1).

    Args:
        magic_link: Magic-link token (SecretStr); validated inside the use case.
        ip_hash: SHA-256 ip hash (primitive).
        name: Guidebook display name (host-supplied or auto-filled, §10.6).
        file_bytes: Raw uploaded file content.
        mime_type: Declared MIME type.
    """

    magic_link: SecretStr
    ip_hash: str
    name: str
    file_bytes: bytes
    mime_type: str


@dataclass(frozen=True)
class IngestionResult:
    """Result of a guidebook upload (spec §8.1).

    Args:
        guidebook_id: UUID string of the created guidebook.
        name: Echoed display name for the UI.
        created_at: ISO-8601 creation timestamp.
    """

    guidebook_id: str
    name: str
    created_at: str

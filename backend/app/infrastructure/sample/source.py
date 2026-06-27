"""Source for the sample-guidebook bytes (composition-only, infrastructure-local).

The sample guidebook is business data living in ``docs/`` (not bundled in app code); its path comes
from ``Settings.sample_guidebook_path`` and the bytes are injected into ``load_sample_chunks`` via
this port, so the preload doesn't hardcode a file location and unit tests can supply a fake. No use
case consumes it, so the port stays here in infrastructure rather than ``application/ports`` (C-31).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SampleGuidebookSource(Protocol):
    """Provides the raw bytes of the sample guidebook."""

    def read(self) -> bytes:
        """Return the sample guidebook file contents."""
        ...


class FileSampleGuidebookSource:
    """Reads the sample guidebook from a filesystem path (the bundled ``docs/`` file)."""

    def __init__(self, path: str) -> None:
        """Init.

        Args:
            path: Filesystem path to the sample guidebook (``Settings.sample_guidebook_path``).
        """
        self._path = Path(path)

    def read(self) -> bytes:
        """Read the file bytes.

        :raises FileNotFoundError: if the path does not exist (cold-start misconfiguration).
        """
        return self._path.read_bytes()

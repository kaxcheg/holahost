"""Source for the sample-guidebook bytes (composition-only, infrastructure-local).

The sample guidebook is business data living in ``docs/`` (not bundled in app code); its path comes
from ``Settings.sample_guidebook_path`` and the bytes are injected into ``load_sample_chunks`` via
this port, so the preload doesn't hardcode a file location and unit tests can supply a fake. No use
case consumes it, so the port stays here in infrastructure rather than ``application/ports`` (C-31).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


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


class S3SampleGuidebookSource:
    """Reads the sample guidebook from an S3 object (staging/prod).

    The sample is business content: storing it in S3 (instead of baking it into the Lambda image) lets
    it change without a redeploy — the next cold start picks up the new object. This adapter DEFINES the
    infra contract: a bucket holding the object (I-09), ``s3:GetObject`` on it for the Lambda execution
    role (I-06/I-12), and the bucket/key injected as Lambda env (I-12).
    """

    def __init__(self, client: S3Client, bucket: str, key: str) -> None:
        """Init.

        Args:
            client: S3 client (see ``infrastructure.boto.clients.make_s3_client``).
            bucket: S3 bucket holding the sample-guidebook object.
            key: Object key of the sample guidebook within ``bucket``.
        """
        self._client = client
        self._bucket = bucket
        self._key = key

    def read(self) -> bytes:
        """Fetch the object bytes from S3.

        :raises botocore.exceptions.ClientError: if the object is missing or access is denied (cold-start
            misconfiguration — bucket, key, or IAM).
        """
        return self._client.get_object(Bucket=self._bucket, Key=self._key)["Body"].read()

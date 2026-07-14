"""Cold-start system-prompt loading from S3 into os.environ (spec §10.3, D-30).

In staging/prod the bootstrap fetches the system prompt from S3 and sets ``os.environ["SYSTEM_PROMPT"]``
BEFORE ``Settings`` is built (``Settings.system_prompt`` is a required field). Storing it in S3 (not the
Lambda env) keeps it out of the 4 KB env limit and lets it change without a redeploy — the next cold
start picks up the new object. Dev sets ``SYSTEM_PROMPT`` inline in ``.env`` and never calls this.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


def load_system_prompt_into_env(client: S3Client, bucket: str, key: str) -> None:
    """Fetch the system-prompt object and set ``os.environ["SYSTEM_PROMPT"]`` (cold start, §10.3).

    :raises botocore.exceptions.ClientError: if the object is missing or access is denied (cold-start
        misconfiguration — bucket, key, or IAM).
    """
    body = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    os.environ["SYSTEM_PROMPT"] = body.decode("utf-8")

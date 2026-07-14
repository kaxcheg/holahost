"""boto3 client factories — region-explicit, lazy import (spec §10.3 / §12.3).

The region is passed explicitly (callers read the app's ``AWS_RESOURCES_REGION`` param) so client
creation never depends on ambient region discovery — distinct from the reserved Lambda-runtime
``AWS_REGION`` (deploy region). ``boto3`` is imported lazily so the dev cold start (which reaches
neither Secrets Manager nor S3) does not pay for it. Shared by the cold-start loaders
(``scripts.sm_loader``, ``scripts.prompt_loader``) and the sample-guidebook S3 adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_secretsmanager import SecretsManagerClient


def make_secrets_client(region: str) -> SecretsManagerClient:
    """Build a Secrets Manager client bound to an explicit region.

    :returns: a boto3 Secrets Manager client bound to ``region``.
    """
    import boto3

    return boto3.session.Session().client("secretsmanager", region_name=region)


def make_s3_client(region: str) -> S3Client:
    """Build an S3 client bound to an explicit region.

    :returns: a boto3 S3 client bound to ``region``.
    """
    import boto3

    # Explicit annotation: mypy resolves the boto3-stubs overload to S3Client; keeps editors from
    # treating the client as partially-unknown without a mypy-redundant cast.
    client: S3Client = boto3.session.Session().client("s3", region_name=region)
    return client

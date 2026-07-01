"""Cold-start composition root for the request Lambda (spec §8.6 / §10.3).

Imported once per Lambda execution environment (SnapStart-frozen). In staging/prod it loads the
server-side secrets into ``os.environ`` BEFORE ``Settings`` is built; then it configures structured
logging and assembles the module-level ``container`` singleton. Dev reads secrets from ``.env`` and
skips Secrets Manager (C-6 / C-7).
"""

from __future__ import annotations

import os

from config.logging import configure_logging
from scripts.sm_loader import load_secrets_into_env, make_secrets_client
from scripts.wiring import Container, build

_env = os.environ["ENV"]  # required; missing ENV → KeyError fail-fast (matches Settings.env)
if _env in ("staging", "prod"):
    # AWS_RESOURCES_REGION — the app's boto region (where SM / S3 live), an app param (Settings field
    # ``aws_resources_region``); read RAW here because the SM client runs before Settings is built. Distinct
    # from the Lambda-runtime AWS_REGION (= the deploy region, set in CI).
    load_secrets_into_env(_env, make_secrets_client(os.environ["AWS_RESOURCES_REGION"]))

configure_logging()
container: Container = build()

"""Cold-start composition root for the request Lambda (spec §8.6 / §10.3).

Imported once per Lambda execution environment (SnapStart-frozen). In staging/prod it loads the
server-side secrets AND the system prompt into ``os.environ`` BEFORE ``Settings`` is built; then it
configures structured logging and assembles the module-level ``container`` singleton. Dev reads
secrets and the prompt from ``.env`` and skips Secrets Manager / S3 (C-6 / C-7, D-30).
"""

from __future__ import annotations

import os

from config.logging import configure_logging
from infrastructure.boto.clients import make_s3_client, make_secrets_client
from scripts.prompt_loader import load_system_prompt_into_env
from scripts.sm_loader import load_secrets_into_env
from scripts.wiring import Container, build

_env = os.environ["ENV"]  # required; missing ENV → KeyError fail-fast (matches Settings.env)
if _env in ("staging", "prod"):
    # AWS_RESOURCES_REGION — the app's boto region (where SM / S3 live), an app param (Settings field
    # ``aws_resources_region``); read RAW here because the SM / S3 clients run before Settings is built.
    # Distinct from the Lambda-runtime AWS_REGION (= the deploy region, set in CI).
    _region = os.environ["AWS_RESOURCES_REGION"]
    load_secrets_into_env(_env, make_secrets_client(_region))
    # SYSTEM_PROMPT is sourced from S3 (not env, not the image) so it changes without a redeploy (D-30);
    # set into os.environ before Settings is built (Settings.system_prompt is required).
    load_system_prompt_into_env(
        make_s3_client(_region),
        os.environ["SYSTEM_PROMPT_S3_BUCKET"],
        os.environ["SYSTEM_PROMPT_S3_KEY"],
    )

configure_logging()
container: Container = build()

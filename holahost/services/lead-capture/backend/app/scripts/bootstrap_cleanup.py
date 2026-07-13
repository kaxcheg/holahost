"""Cold-start composition root for the cleanup Lambda (spec §8.6 / §4.7 / §10.3).

EventBridge-triggered. In staging/prod it loads the server-side secrets into ``os.environ`` before
``Settings`` is built, configures structured logging, then assembles the module-level cleanup
``container``. ``lambda_handler`` runs both cleanup use cases and returns the totals. Uses none of the
HTTP stack (router / request parsing / response envelope).
"""

from __future__ import annotations

import os
from typing import Any

from config.logging import configure_logging
from scripts.cleanup_wiring import build_cleanup, run
from scripts.sm_loader import load_secrets_into_env

_env = os.environ["ENV"]  # required; missing ENV → KeyError fail-fast (matches Settings.env)
if _env in ("staging", "prod"):
    import boto3

    load_secrets_into_env(_env, boto3.session.Session().client("secretsmanager"))

configure_logging()
container = build_cleanup()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, int]:
    """EventBridge entry point: run the cleanup use cases and return the deletion totals."""
    return run(container)

"""Registering this service's exception handlers on a bare test app.

`create_edge_app` does this for the real application, from the same three declarations.
A test that builds a minimal app — routes only, or one middleware under examination —
still needs the handlers, or every published error comes back `500` and the test is
measuring the wrong thing.

Here rather than repeated in each test module, and spelled out rather than hidden behind a
service-side wrapper: both facts are declared once, in `interface/http/errors.py`, and the
composition root passes those same two to the factory.
"""

from __future__ import annotations

from fastapi import FastAPI
from holahost_http import register_error_handlers

from interface.http.errors import ERROR_CONTRACT, SILENT_500_TYPES


def register_test_handlers(app: FastAPI) -> None:
    register_error_handlers(
        app,
        contract=ERROR_CONTRACT,
        silent_500_types=SILENT_500_TYPES,
    )

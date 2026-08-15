"""FastAPI application factory (ticket R-20/R-24 boundary — this is where the pieces
built by Tasks 4-10 get assembled into one app; `scripts/bootstrap.py`, Task 12, calls
this after settings/secrets/logging are ready).
"""

from __future__ import annotations

from fastapi import FastAPI

from interface.http.errors import register_error_handlers
from interface.http.health import router as health_router
from interface.http.middleware import RequestIdMiddleware
from interface.http.router import router as documents_router


def create_app() -> FastAPI:
    app = FastAPI(title="rag-documents")
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(documents_router)
    return app

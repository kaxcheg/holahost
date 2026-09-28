"""The JWKS endpoint the services validate against — all of `auth` that dev needs served.

Standard-library HTTP is enough: one static document, fetched by the services' JWKS clients on
their first validation and again only on an unknown `kid`.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from dev_minter.keys import SigningKey

JWKS_PATH = "/.well-known/jwks.json"
PORT = 8081

# The caching hint `auth`'s own JWKS endpoint sends (the platform specification).
_CACHE_CONTROL = "max-age=300"


def jwks_document(key: SigningKey) -> bytes:
    """The JWKS body: the key's public half, and only that."""
    return json.dumps({"keys": [key.public_jwk()]}).encode()


def make_server(jwks: bytes, *, host: str, port: int) -> ThreadingHTTPServer:
    """A server answering `GET /.well-known/jwks.json` with `jwks` and 404 to anything else."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if urlsplit(self.path).path != JWKS_PATH:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(jwks)))
            self.send_header("Cache-Control", _CACHE_CONTROL)
            self.end_headers()
            self.wfile.write(jwks)

    return ThreadingHTTPServer((host, port), _Handler)

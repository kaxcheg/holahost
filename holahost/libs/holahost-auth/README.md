# holahost-auth

Offline JWT validation for Holahost services — a shared platform library, not a standalone
service (ADR A-5 of the `rag-documents` spec). Ships as a Poetry path-dependency, consumed
directly rather than published:

```toml
# a consuming service's pyproject.toml
[tool.poetry.dependencies]
holahost-auth = { path = "../../libs/holahost-auth", develop = true }
```

## What it does

Implements the platform's numbered offline JWT-validation procedure (see `holahost_frame.md`,
"Аутентификация и авторизация"): scheme check, parse, `alg` pinning (never read from the token
itself), signature verification by `kid` against a cached JWKS (with a single re-fetch if `kid` is
unknown), standard claims (`exp`/`iat`/`iss`/`aud`, with configurable clock skew), and
`sub == client_id` discrimination between service, user, and delegated (token-exchange) tokens.

**What it does not do:** authorization. On success it returns a `TokenContext`; deciding whether
that subject/roles combination has the right to do what the endpoint is about to do (403) is
entirely the consuming endpoint's job, never this library's.

## Usage

```python
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from holahost_auth import AuthConfig, AuthenticationError, HolahostAuth, JwksUnavailableError, TokenContext

app = FastAPI()

auth = HolahostAuth(
    AuthConfig(
        jwks_url="https://auth.holahost.internal/.well-known/jwks.json",
        expected_algorithm="RS256",
        expected_issuer="auth",
        expected_audience="rag-documents",
        clock_skew_seconds=30,
    )
)


# HolahostAuth raises its own exception types — mapping them to a status code
# and response shape is this service's own call, not the library's (see "Errors").
@app.exception_handler(AuthenticationError)
def _handle_auth_error(request: Request, exc: AuthenticationError) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


@app.exception_handler(JwksUnavailableError)
def _handle_jwks_unavailable(request: Request, exc: JwksUnavailableError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Service Unavailable"})


@app.get("/documents/{document_id}")
def get_document(document_id: str, ctx: Annotated[TokenContext, Depends(auth)]) -> dict:
    ...  # ctx.subject / ctx.client_id / ctx.roles / ctx.act are available here


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}  # not behind `auth` — no token required
```

Instantiate `HolahostAuth` once per service, at the composition root — its JWKS client is safe to
reuse for the process's lifetime. Apply `Depends(auth)` to every router except health checks;
there is no path-exclusion mechanism inside the library itself, by design — a route simply isn't
declared under the auth-guarded router.

## `AuthConfig` fields

All fields are required; there are no library-side defaults.

| Field | Meaning |
|---|---|
| `jwks_url` | URL of the JWKS endpoint (`auth`'s `/.well-known/jwks.json`, or the dev-minter's during local development) |
| `expected_algorithm` | The single signing algorithm this service accepts (e.g. `"RS256"`) |
| `expected_issuer` | Expected `iss` claim value |
| `expected_audience` | Expected `aud` entry for this service |
| `clock_skew_seconds` | Allowed leeway when checking `exp`/`iat` |

## Errors

`HolahostAuth.__call__` raises its own typed exceptions directly — it does **not** translate them
to `fastapi.HTTPException` itself. Mapping exception type to an HTTP status/response shape is the
consuming service's own interface-layer decision, the same rule every other port/library in the
platform follows (a port raises typed, protocol-agnostic exceptions; the *consumer's* interface
layer owns type → HTTP-status dispatch). The consuming service must register its own exception
handlers for both types below — see `tests/test_dependency.py`'s `build_app()` for a minimal
example, or `rag-documents`' own `interface/http/errors.py` for a real one.

Every *per-token* validation failure raises a single `AuthenticationError` (`reason` is for the
caller's own logging, never for a response body — nothing in this library's own behavior discloses
it). The platform convention is to map this to `401` with no reason in the body. There is no `403`
from this library.

A JWKS-endpoint outage or malformed response raises `JwksUnavailableError` instead — deliberately
kept distinct, since it would reject *every* token, not just the one being checked. The platform
convention maps this to `503`, not `401`: an infra incident must not look like "invalid
credentials" to callers.

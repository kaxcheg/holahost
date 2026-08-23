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
`sub == client_id` discrimination between service, user, and delegated (token-exchange) tokens
(exposed as `TokenContext.is_service_token`, which is what a rate limiter keys its ceilings on).

**What it does not do:** authorization. On success it returns a `TokenContext`; deciding whether
that subject/roles combination has the right to do what the endpoint is about to do (403) is
entirely the consuming endpoint's job, never this library's.

## Usage

```python
from typing import Annotated

from fastapi import Depends, FastAPI
from starlette.middleware import Middleware

from holahost_auth import AuthConfig, HolahostAuthMiddleware, TokenContext, current_token

app = FastAPI(
    middleware=[
        Middleware(
            HolahostAuthMiddleware,
            config=AuthConfig(
                jwks_url="https://auth.holahost.internal/.well-known/jwks.json",
                expected_algorithm="RS256",
                expected_issuer="auth",
                expected_audience="rag-documents",
                clock_skew_seconds=30,
            ),
            public_paths=("/api/rag-documents/health",),
        )
    ]
)


@app.get("/api/rag-documents/documents/{document_id}")
def get_document(document_id: str, ctx: Annotated[TokenContext, Depends(current_token)]) -> dict:
    ...  # ctx.subject / ctx.client_id / ctx.roles / ctx.act are available here


@app.get("/api/rag-documents/health")
def health() -> dict:
    return {"status": "ok"}  # listed in public_paths — no token required
```

Two pieces, one validation path:

- **`HolahostAuthMiddleware`** validates the token *before routing* and stores the result at
  `scope["state"]["token"]`. Add it once, at the composition root; the JWKS client it builds is
  safe to reuse for the process's lifetime.
- **`current_token`** is a plain FastAPI dependency that reads what the middleware stored. It never
  validates. On a route the middleware did not cover it raises `RuntimeError` — a wiring defect,
  which must not be reported to the caller as `401`.

### Why validation is middleware and not a dependency

A framework resolves the request body while building an endpoint's arguments, which happens
*before* it resolves that endpoint's dependencies. Authentication expressed as `Depends(auth)`
therefore runs *after* a multipart upload has already been read in full: an anonymous 50 MiB POST
is received end to end and only then answered `401`. Validating ahead of routing is what makes
"reject before reading" possible at all.

Exclusions are explicit (`public_paths`) rather than structural, because middleware wraps the whole
app: there is no "router this isn't declared under" to opt out by.

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

The middleware answers both failures itself and registers nothing on the app. It has to: an
exception raised in middleware never reaches `@app.exception_handler` — those are bound to
Starlette's `ExceptionMiddleware`, which sits *inside* the user-middleware stack — so it would
surface as a `500`. A consuming service therefore registers no handler for either type below.

Neither response body carries a reason. Pass `on_rejected` (a `holahost_http.RejectionLogger`) to
receive the cause and the request scope, and write the service's own log line for the refusal —
without it the rejection still happens, but nothing downstream runs to record it.

Every *per-token* validation failure raises a single `AuthenticationError` (`reason` is for the
caller's own logging, never for a response body — nothing in this library's own behavior discloses
it). The platform convention is to map this to `401` with no reason in the body. There is no `403`
from this library.

A JWKS-endpoint outage or malformed response raises `JwksUnavailableError` instead — deliberately
kept distinct, since it would reject *every* token, not just the one being checked. The platform
convention maps this to `503`, not `401`: an infra incident must not look like "invalid
credentials" to callers.

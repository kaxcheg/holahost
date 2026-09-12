# holahost-auth

Offline JWT validation for Holahost services. One shared library rather than a copy per service:
this is a security check, and N implementations of it drift. Consumed as a
[path dependency](../../README.md#shared-libraries).

## What it does

Implements the platform's offline JWT-validation procedure: scheme check, parse, `alg` pinning
(never read from the token itself), signature verification by `kid` against a cached JWKS (with a
single re-fetch if `kid` is unknown), standard claims (`exp`/`iat`/`iss`/`aud`, with configurable
clock skew), and
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
            config=AuthConfig(),  # reads its own five variables — see Configuration
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

The same reason every edge check is — a framework reads the request body before resolving an
endpoint's dependencies, so `Depends(auth)` answers `401` only after the whole upload has been
received. See [`holahost-http`](../holahost-http/README.md#why-these-live-in-a-library-and-not-in-a-service).

Exclusions are explicit (`public_paths`) rather than structural, because middleware wraps the whole
app: there is no "router this isn't declared under" to opt out by.

## Configuration

One object, not two. `AuthConfig` is both the shape of the environment and what the
validator wants, and it loads itself:

```python
# app/interface/http/dependencies.py
from holahost_auth import AuthConfig


def get_auth_config() -> AuthConfig:
    return AuthConfig()
```

| Environment variable | Meaning |
|---|---|
| `JWKS_URL` | URL of the JWKS endpoint (`auth`'s `/.well-known/jwks.json`, or the dev-minter's during local development) |
| `EXPECTED_ALGORITHM` | The single signing algorithm this service accepts (e.g. `"RS256"`) |
| `EXPECTED_ISSUER` | Expected `iss` claim value |
| `EXPECTED_AUDIENCE` | Expected `aud` entry for this service |
| `JWT_CLOCK_SKEW_SECONDS` | Allowed leeway when checking `exp`/`iat` |

The field names are the variable names, lower-cased. That is the whole mapping rule, and
having no second spelling is the point. A settings class, a config class and a hand-written
function between them would be three declarations of one fact, and the function is the half
that fails silently: drop `clock_skew_seconds` from it and the service rejects valid tokens
at the `exp` boundary whenever a clock drifts, with nothing in a log to say why.

The variables are a platform contract rather than a per-service choice: every service
validates tokens from the same issuer against the same JWKS, and the only value that
differs is `EXPECTED_AUDIENCE`. So they are declared here, once, and **not** mixed into a
service's own `Settings` — a middleware handed an object that also carries a database
password sees more than it needs to.

All five are required and none has a default, empty strings included. An authentication
parameter a service forgot to set must stop it starting, not fall back to something
plausible. The object is frozen: nothing should move an authentication parameter under a
middleware that holds it for the life of the process.

Arguments take precedence over the environment, which is how a test builds one:

```python
AuthConfig(
    jwks_url="https://auth.example/.well-known/jwks.json",
    expected_algorithm="RS256",
    expected_issuer="auth",
    expected_audience="rag-documents",
    jwt_clock_skew_seconds=30,
)
```

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

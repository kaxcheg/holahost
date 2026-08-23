# holahost-http

The HTTP edge shared by Holahost services: the error envelope, and the checks that
have to happen before a request reaches a route handler.

Consumed as a Poetry path dependency:

```toml
holahost-http = { path = "../../../libs/holahost-http", develop = true }
```

## Why these live in a library and not in a service

A framework resolves a request body before it resolves the endpoint's dependencies.
For a multipart upload that means `await request.form()` — the full read — runs
*ahead of* authentication, rate limiting, and any size check written as a `Depends`.
A service that expresses those checks the framework-native way therefore accepts every
byte of an oversized, unauthenticated, over-quota upload and only then refuses it.
This was not theoretical: a 50 MiB POST with no `Authorization` header was measured
being read in full before the 401.

Nothing a service writes inside its own routes fixes that. The checks have to sit
outside routing, which means plain ASGI middleware — the same three for every service,
which is what makes them a library rather than a pattern to re-derive.

## What it provides

| Piece | What it does |
|---|---|
| `RequestIdMiddleware` | Reads `X-Request-ID`, starts the request timer, echoes the header back. Never synthesizes one; refuses a request that arrived without it when given the service's own error. |
| `BodySizeLimitMiddleware` | 413 on `Content-Length` over the cap without reading the body; counts bytes for `chunked`, where no header exists to check. |
| `body_cap_for_upload` | Derives that cap from a service's own file-size limit, adding `MULTIPART_OVERHEAD_ALLOWANCE`. |
| `RateLimitMiddleware` | Consults the limiter before routing, so an over-quota caller is refused while its body is still on the wire. 429 + `Retry-After`. |
| `RateLimiter` / `InMemoryRateLimiter` | The port and a process-local, LRU-bounded implementation. |
| `PlatformError`, `error_envelope`, `send_platform_error` | The envelope `{"error": {code, message, details}}`, and writing it from middleware. |

## What it does not provide

**The error taxonomy.** Which codes exist and which status each maps to is a service's
own contract. This library defines the envelope's *shape* and the base class a service's
error hierarchy inherits (`code` + `details_dict()`), plus the two codes its own
middleware emit — `ERR_PAYLOAD_TOO_LARGE` and `ERR_RATE_LIMIT`. A service keeps its own
`ApplicationError` hierarchy and inherits `PlatformError` from it.

**HTTP status on the exception.** `PlatformError` carries none. The same code can be two
statuses depending on where it was raised — `ERR_PAYLOAD_TOO_LARGE` is 413 for a body
refused unread and 422 for parsed content that turned out too large — so status is
decided where the response is written, not stored on the error.

**The `X-Request-ID` rejection's code.** The *rule* — every real entry path attaches the
header, so its absence means a misconfigured caller — is platform-wide and lives here.
What that violation is called on the wire is not: `RequestIdMiddleware` takes the error
and status as arguments, because this library has no taxonomy to draw a code from. Pass
no error and it observes without ever rejecting.

**Log lines.** Middleware answers a request without reaching the service's handlers, so
the service's own completion-log line would go missing. Each middleware takes an
optional `on_rejected` callback (`RejectionLogger`) and hands back the scope and the
outcome code; the service writes the line in its own shape.

## Middleware order

Pass them to the app constructor, outermost first — that ordering is the contract:

```python
FastAPI(middleware=[
    Middleware(RequestIdMiddleware, ...),      # transport contract, before credentials
    Middleware(BodySizeLimitMiddleware, ...),  # before anything reads the body
    Middleware(HolahostAuthMiddleware, ...),   # holahost-auth
    Middleware(RateLimitMiddleware, ...),      # needs the caller auth put in scope["state"]
])
```

`app.add_middleware()` builds the stack in the reverse of call order, which makes the
resulting order easy to get backwards; the constructor argument reads top-down.

## Deriving the body cap

`BodySizeLimitMiddleware` measures the **whole request body**, multipart framing included;
a service's own limit measures the **file inside it**. Passing the file limit straight
through as `max_bytes` therefore rejects a file of exactly that size, with a 413 that
depends on how many bytes of boundary the client happened to send:

```python
MAX_REQUEST_BODY_SIZE = body_cap_for_upload(MAX_UPLOAD_SIZE)
```

The result is an outer bound for the edge, not a replacement for the service's exact check
on the file it extracted — that check is what a caller is told it exceeded, this one only
decides how much gets read before anyone can look.

## Rate-limit ceilings

`RateLimiter.check` takes `is_service`, so ceilings are keyed by `(bucket, is_service)`.
A service token's quota covers the whole client; an exchanged token's covers one user of
that client. One ceiling for both would either starve a busy client or hand every user
of it the aggregate allowance.

`is_service` is passed in rather than computed from `subject == client_id` inside the
limiter: that equivalence is a fact about the token model, and it already has an owner
in `holahost-auth`.

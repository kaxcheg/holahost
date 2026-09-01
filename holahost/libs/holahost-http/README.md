# holahost-http

The HTTP edge shared by Holahost services, in two halves: the checks that have to happen
before a request reaches a route handler, and the mapping from an exception to the error
envelope once a route has raised.

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

Nothing written inside a route fixes that: the checks have to sit outside routing, which
means plain ASGI middleware — the same three for every service.

The handler half is here for a different reason: nothing about it is inventive and every
part is easy to get subtly wrong — answering an unpublished subclass as its published
ancestor rather than putting an undocumented identity on the wire; keeping the vocabulary
closed so an unmapped exception cannot leak a message; echoing `X-Request-ID` from the one
handler Starlette binds outside the user middleware; keeping a chosen exception out of that
handler, which re-raises after writing.

## What it provides

| Piece | What it does |
|---|---|
| `RequestIdMiddleware` | Reads `X-Request-ID`, starts the request timer, echoes the header back. Never synthesizes one; refuses a request that arrived without it when given the service's own error. |
| `BodySizeLimitMiddleware` | 413 on `Content-Length` over the cap without reading the body; counts bytes for `chunked`, where no header exists to check. |
| `body_cap_for_upload` | Derives that cap from a service's own file-size limit, adding `MULTIPART_OVERHEAD_ALLOWANCE`. |
| `RateLimitMiddleware` | Consults the limiter before routing, so an over-quota caller is refused while its body is still on the wire. 429 + `Retry-After`. |
| `RateLimiter` / `InMemoryRateLimiter` | The port and a process-local, LRU-bounded implementation. |
| `PlatformError`, `error_envelope`, `send_platform_error` | The envelope `{"error": {code, message, details}}`, and writing it from middleware. |
| `MalformedRequestError`, `InvalidPayloadError`, `NotFoundError` | The three errors every service answers with, so their identity and `details` are one thing platform-wide. |
| `register_error_handlers` | Exception -> envelope, driven by the service's own `contract`. |
| `holahost_http.error_schemas` | The published models for the errors above, the `{"error": ...}` wrapper and the strict base a service's own models inherit. |
| `bearer_scheme` | The declaration that puts `bearerAuth` in a service's OpenAPI document. Declares, never enforces. |
| `log_rejection` | The `on_rejected` callback the middleware take, writing the platform's `op_completed` event. |
| `create_edge_app` | Builds the application with the stack in the one order that works, every router under the base path, and the handlers registered. |

## What it does not provide

**The error taxonomy.** Which errors exist and which status each maps to is a service's
own contract, passed to `register_error_handlers` as `contract`. This library defines the
envelope's *shape*, the base class a service's error hierarchy inherits (`code` +
`details_dict()`), the two errors its own middleware raise (`PayloadTooLargeError`,
`RateLimitExceededError`) and the three every service turned out to need verbatim
(`MalformedRequestError`, `InvalidPayloadError`, `NotFoundError`). Everything else — a
service's own sizes, formats and domain refusals — stays in the service.

**An error's identity is its class name**, verbatim: `code` returns
`type(self).__name__`. Identity and the shape of `details` then live on one class, and a
value read out of a log greps back to the code that produced it. Renaming an error class
is a change to the wire contract, and should be reviewed as one.

**HTTP status on the exception.** `PlatformError` carries none. Where an error is raised
decides its status — a body refused unread is 413, parsed content that turned out too
large is 422 — so status is decided where the response is written, not stored on the
error.

**The `X-Request-ID` rejection's code.** The *rule* — every real entry path attaches the
header, so its absence means a misconfigured caller — is platform-wide and lives here.
What that violation is called on the wire is not: `RequestIdMiddleware` takes the error
and status as arguments, because this library has no taxonomy to draw a code from. Pass
no error and it observes without ever rejecting.

**Where the log line goes.** Middleware answers a request without reaching the service's
handlers, so the completion-log line would go missing. Each middleware takes an optional
`on_rejected` callback (`RejectionLogger`) and hands back the scope and the outcome code.
Its *shape* is the platform's — `log_rejection` writes it — but the middleware do not
reach for that themselves: a service assembling the stack by hand chooses, and one that
passes nothing gets silence rather than a surprise dependency.

## Middleware order

The order is the contract, and `create_edge_app` is what enforces it — a service supplies
*what* runs, never *when*:

```python
app = create_edge_app(
    title="rag-documents",
    description=DESCRIPTION,
    api_base_url="/api/rag-documents",
    routers=[health_router, documents_router],
    authentication=Middleware(               # holahost-auth, built by the service
        HolahostAuthMiddleware,
        config=AuthConfig(),
        public_paths=(HEALTH_PATH,),         # also what exempts these from X-Request-ID
    ),
    rate_limiter=get_rate_limiter(),
    bucket_for=bucket_for,
    max_request_body_size=body_cap_for_upload(MAX_UPLOAD_SIZE),
    reported_body_limit=MAX_UPLOAD_SIZE,
    missing_request_id_error=MalformedRequestError(),
    error_contract=ERROR_CONTRACT,           # the service's table, as data
    silent_500_types=(DomainValidationError,),
)
```

Resulting stack, outermost first, every position load-bearing:

| | Why there |
|---|---|
| `RequestIdMiddleware` | outermost, so a refusal by anything below still carries the caller's correlation id |
| `BodySizeLimitMiddleware` | before anything reads the body — see above |
| authentication | the only writer of `scope["state"]["token"]` |
| `RateLimitMiddleware` | keys on that token; above authentication it finds no caller and raises |

Written out per service that is four lines a reviewer checks by eye, and
`app.add_middleware()` — the idiom a reader reaches for — builds the stack in reverse.

Authentication arrives already built because `holahost-auth` depends on this package and
not the other way round; the factory only decides where it sits. Its `public_paths` is the
single declaration of what needs no token, read back to exempt the same paths from the
`X-Request-ID` requirement — two lists would diverge silently in both directions.

There is no `on_rejected` argument above, and no logger: nothing about a rejection event
is the service's, so the factory gives `log_rejection` to all four middleware and the
library imports `holahost_observability.log_event` itself. An `authentication` built
carrying its own `on_rejected` is refused at build time rather than splitting the event
into two shapes.

Two more omissions the factory closes: every router is mounted under `api_base_url` (one
that forgets the prefix is unreachable through the gateway, and for a health route that
means the deploy's smoke check never finds it), and the exception handlers are always
registered — an app with its edge in place and no mapping answers 500 to every error the
service publishes, and looks entirely healthy until one is raised.

The contract arrives as **data**, not as a "register the handlers" callback: the function
that consumes it (`register_error_handlers`) lives in this package too. It stays exported
for a test that builds a bare app without the edge.

## Deriving the body cap

`BodySizeLimitMiddleware` measures the **whole request body**, multipart framing included;
a service's own limit measures the **file inside it**. Passing the file limit straight
through as `max_bytes` therefore rejects a file of exactly that size, with a 413 that
depends on how many bytes of boundary the client happened to send:

```python
Middleware(
    BodySizeLimitMiddleware,
    max_bytes=body_cap_for_upload(MAX_UPLOAD_SIZE),  # what the edge enforces
    reported_limit=MAX_UPLOAD_SIZE,                  # what a 413 advertises
)
```

The result is an outer bound for the edge, not a replacement for the service's exact check
on the file it extracted — that check is what a caller is told it exceeded, this one only
decides how much gets read before anyone can look.

Hence two arguments: `max_bytes` is the transport number, `reported_limit` is what the
caller acts on. Advertising the transport cap sends a client that trims to it just above
the service's own limit, to be refused a second time with a different `limit`.
`reported_limit` defaults to `max_bytes`, correct for a service that caps a body it does
not otherwise check.

## Rate-limit ceilings

`RateLimiter.check` takes `is_service`, so ceilings are keyed by `(bucket, is_service)`.
A service token's quota covers the whole client; an exchanged token's covers one user of
that client. One ceiling for both would either starve a busy client or hand every user
of it the aggregate allowance.

`is_service` is passed in rather than computed from `subject == client_id` inside the
limiter: that equivalence is a fact about the token model, and it already has an owner
in `holahost-auth`.

## Registering the handlers

```python
register_error_handlers(
    app,
    contract={UploadTooLargeError: 413, InvalidPayloadError: 422, NotFoundError: 404},
    silent_500_types=(DomainValidationError,),
)
```

`contract` is the whole of what a service decides. Membership settles three things at
once: the status, whether the caller learns anything, and whether the identity reaches the
wire. Anything absent is answered `500 InternalError` with an empty body, which keeps the
published vocabulary closed while Python's exception space stays open.

Lookup walks the MRO, so an unlisted subclass answers as the published error it
specialises, with the **ancestor's** identity: its own name is in no schema.

Every refusal is logged, through `holahost_observability.log_event` — not a parameter,
because nothing about the line is the service's. On a 4xx the cause is already in the
envelope's `details`; on a 5xx the body deliberately carries nothing, so `error_reason`
on this line is the only place it survives.

`silent_500_types` names extra types answered `500` through an ordinary handler. Without
it they reach Starlette's bare-`Exception` handler, bound to `ServerErrorMiddleware`, which
**re-raises after writing the response** — so uvicorn prints a traceback outside the JSON
log and its scrubbing. A service's domain-invariant error is the usual member.

A `contract` with no `InvalidPayloadError` is refused at registration: the framework's own
validation can reject a request before any route runs — on a path or query parameter, so a
service with no request bodies is not exempt — and that is the error it is answered with.

## What is published, and what is not

`message` is on the wire and in **no** schema. It is for a person reading a log or a
response by hand; a consumer branches on `code` and composes what it shows from `details`.
Publishing it would invite exactly the parsing the contract says not to do.

The platform's middleware answers — `401`/`503` from `holahost-auth`, `429` and the
transport `413` from here — are described in no service's document either. They are
identical behind every service, and restating one fact in N documents makes it N facts
that drift.

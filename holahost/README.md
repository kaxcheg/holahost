# Holahost platform

Backend of Holahost: HTTP microservices on one Docker network, deployed to a single EC2 instance
behind an API Gateway. Services talk synchronously over HTTP — no broker, no event integration. Each
is an independent deploy unit owning its ECR repository, Terraform roots and pipelines, so rolling
one out touches nothing else.

## Service types

| Type | Role |
|---|---|
| **Authorization Service** (`auth`) | The platform's JWT issuer and only authentication point. Holds user identities and global `roles`; issues user tokens (authorization code + PKCE), service tokens (`client_credentials`) and delegated tokens (token exchange, RFC 8693). |
| **Resource Service** | A narrow domain with little business logic. Owns data or fronts an external provider, and validates tokens. `rag-documents` and `llm-client` are Resource Services. |
| **Orchestration Service** | Implements a product's backend: validates tokens and orchestrates calls to Resource Services on behalf of a user, through token exchange. |

## How a request reaches a service

```
browser / caller → CloudFront → API Gateway → nginx (on the instance) → <svc>:8080
```

The gateway applies global throttling and adds a static `x-origin-secret` header; nginx checks that
header, applies a per-IP `limit_req`, stamps `X-Request-ID` and resolves the service by name on the
shared `backbone` Docker network. **The gateway does not authenticate** — every service validates
the JWT itself, offline, against cached JWKS.

On `dev` there is no gateway and no nginx: the service publishes its port on the host and callers
set `X-Request-ID` themselves. A service behaves identically either way — no environment branches,
and it compensates for nothing the perimeter would otherwise do.

## The contract every microservice satisfies

- The container listens on **8080** and is never published outside the instance.
- `API_BASE_URL = /api/<svc>` — the path segment is the service name, and so are the container name
  on `backbone` and the ECR repository name.
- Every route lives under that base path, **including `GET <API_BASE_URL>/health`**. The gateway
  routes by prefix and does not rewrite the path, so a route published at a bare `/health` is
  unreachable from outside and the deploy smoke check never gets to it.
- JWT is validated **offline** on every route except health, by the `holahost-auth` middleware.
- Errors use one envelope: `{"error": {"code", "message", "details"}}`.
- The service publishes an OpenAPI document and versions it in the repo.
- Compose uses `networks: [backbone]` (external) and `restart: unless-stopped`.

## The HTTP edge

The middleware stack is fixed by `holahost_http.create_edge_app` and is not a per-service choice:

```
RequestId → BodySize → Auth → RateLimit → routing
```

Each service declares *what* runs — its authentication middleware, rate limiter, route-to-bucket map,
body cap and routers; the factory decides the order. Why each position is load-bearing, and why these
are middleware rather than dependencies, is in [`libs/holahost-http`](libs/holahost-http/README.md).

**Observability is one structured log event per request**, successful or not — there is no metrics
agent and no Prometheus in the topology:

```
op_completed { request_id, client_id, sub, route, outcome, duration_ms, error_reason? }
```

`outcome` is the identity of a refusal; every CloudWatch filter matches on it. A service adds its own
fields through an allowlist — see [`libs/holahost-observability`](libs/holahost-observability/README.md).

## Shared libraries

Consumed as Poetry path dependencies; they are not published to an index. Dependencies run one way:
`observability → http → auth`; `db` depends on none of them.

| Library | What it provides |
|---|---|
| [`holahost-observability`](libs/holahost-observability/README.md) | JSON logger, field allowlist, the `op_completed` core, free-text scrubber |
| [`holahost-http`](libs/holahost-http/README.md) | Error envelope and `PlatformError`; the `X-Request-ID`, body-limit and rate-limit middleware; the `RateLimiter` port and its in-memory implementation; the `create_edge_app` factory |
| [`holahost-auth`](libs/holahost-auth/README.md) | Offline JWT validation middleware, `TokenContext`, `AuthConfig` |
| [`holahost-db`](libs/holahost-db/README.md) | The three storage-failure types and driver-error translation, the `UnitOfWork` port and its SQLAlchemy implementation, engine factory, retry-on-conflict, RLS binding and the startup guard, app-role provisioning |

To consume one, add a path dependency:
`holahost-http = { path = "../../../libs/holahost-http", develop = true }`.

## Layout

| Path | What lives there |
|---|---|
| `services/<svc>/` | A microservice: `backend/`, `Dockerfile`, compose files, `infra/`, `docs/openapi.json` |
| `libs/<lib>/` | Shared platform libraries |
| `tools/<tool>/` | Console tools. Not deploy units — no image, no ECR |
| `templates/service/` | The skeleton a new service is copied from |
| `infra/modules/` | Terraform modules the services' own roots call |
| `make/common.mk` | Make targets every service includes |

Service infrastructure lives in the service's own Terraform roots, **one directory per environment**
(`infra/common` for the ECR repository, `infra/envs/<env>` for secrets, log group and alarms) rather
than one root with workspaces: environments differ in which resources exist and who may touch them,
not only in variable values.

## Where this is designed to grow

Each extension has a trigger rather than a date: async work inside a service (a scenario stops
fitting the gateway's 30-second ceiling), persistent rate-limit counters (a second replica, or a
quota that becomes contractual), horizontal scaling, direct browser access to a Resource Service,
per-resource grants beyond owner-only, an ORM (a real aggregate appears), and a platform-wide event
architecture (one domain fact gets a third consumer).

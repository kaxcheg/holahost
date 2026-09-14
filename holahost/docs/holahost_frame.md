# Holahost — framework specification

The framework specification from which the individual specifications for Holahost's backend
microservices are written.

**Holahost** is a product combining several capabilities — a classic PMS, an AI chat assistant,
internal services and others.

**The Holahost backend** is a set of microservices on one network:
  - The microservices fall into three kinds:
    - **Authorization Service** (`auth`) — the JWT issuer, the single point of authentication and of
      basic authorization; kept as a kind of its own (see "Authentication and authorization").
    - **Resource Services** (rag-documents, llm-client and others) — a narrow domain and a minimum of
      business logic; they host resources (their own data, or access to an external provider) and
      validate tokens.
    - **Orchestration Services** — they implement the backend of Holahost's products; they validate
      tokens and orchestrate calls to Resource Services (on behalf of a user, through token exchange)
      and to the Authorization Service.

# Tech constraints

System architecture:
  - backend microservices on docker compose plus a shared docker network on EC2
  - Communication between microservices is synchronous HTTP; there is no event integration.
  - **Authorization Service** (`auth`) — the JWT issuer: user login by Authorization Code + PKCE +
    refresh, s2s by client_credentials (as-itself) and token exchange (on-behalf-of-user). The API
    Gateway does not do authentication; every service validates the JWT offline. AuthZ: basic (`aud`,
    `roles`) in `auth`, fine-grained (rights over resources) in the Resource Service.
  - Rate limiting is layered (gateway-wide throttling → nginx per-IP `limit_req` → per-service
    in-memory by `client_id`+`sub`); the contract on exceeding it is 429 + `Retry-After`. See
    "Brief: rate limiting".
  - Tracing: an end-to-end `X-Request-ID` — nginx puts it on the request headers that reach the
    service; every service logs it and propagates it into all outgoing inter-service calls.

Code architecture: Clean architecture

Domain modelling: lightweight DDD (without event integration) / frozen dataclass

Infrastructure stack: AWS EC2, ECR, API Gateway

# Platform-wide extensions

Extensions applicable to any microservice on the platform. A service's specification **references**
an entry and adds only what is its own: why it needs this, and what changes in its contract. The
format of an entry is: why and under what conditions → decision → what changes → trigger. While an
entry is here, the extension does not exist in code — no flags, no stubs.

## S-1. Asynchronous execution inside a service

**Why.** Synchronous HTTP is bounded by the API Gateway's integration ceiling (30 s). Anything that
does not fit inside it — heavy processing, batch operations, reindexing — has to run outside the
request. On top of that, a synchronous path loses its result when the connection drops and cannot
retry by itself.

**Decision.** A queue and a worker **inside the service**, not at platform level: inter-service
communication stays synchronous HTTP, and no separate deferred-work service is introduced.
- **Minimal variant:** a task table in the service's own Postgres, selected with `SELECT … FOR UPDATE
  SKIP LOCKED`; the worker is a second container of the same image with a different start command.
  The task is enqueued in the same transaction as the state change, so atomicity is free.
- **Variant with a broker:** RabbitMQ as a container in **that service's own** compose project
  (private, not exposed on `backbone`). Direct exchange → a durable quorum queue per task type;
  retries are TTL buckets with dead-lettering back into the working queue; exhausted attempts → DLQ.
  A message carries only an identifier and an attempt number, while the payload stays in the
  database. `message_id` is for deduplication, `correlation_id` is the initiator's `X-Request-ID`, so
  that end-to-end tracing does not break at the queue boundary. Enqueuing goes through an outbox
  table in one transaction with the state change: without it, a crash between the commit and the
  publish leaves the task lost forever.

The guarantee in both variants is at-least-once, so the handler must be idempotent. The source of
truth is the state in the database; the queue is only the signal that it is time. A background task
inside the API process is rejected: it is lost on restart, it competes for CPU with online requests,
and it has no retries.

**What changes.** The contract becomes two-phase (enqueue → identifier → read the result or the
status). The main consequence is usually not the queue but the data: **the service starts storing a
payload** — the task's input and its result have to sit somewhere until they are collected, which
brings TTLs, ownership of the result, and the question of encryption at rest.

**Trigger.** The first scenario that consistently fails to fit the synchronous budget. Moving from a
table to a broker is justified once there is more than one worker and the database starts being the
bottleneck, or once priorities and routine DLQ triage are needed. If a **second** service needs a
broker, a private broker is a dead end — that is already S-7.

## S-2. Persistent rate-limit counters

**Why.** Counters in process memory are zeroed by a restart and are not shared between replicas.
While the limit protects the service from overload this is acceptable; as soon as it becomes a
promise ("N requests a day by contract"), or the window becomes long relative to how often the
service is deployed, the reset turns into a defect.

**Decision.** Storage outside the process: Redis (atomic increments with TTL, a deploy unit of its
own) or a table in the service's own Postgres (no new component, at the cost of a database write per
request).

**What changes.** Nothing in the contract: the codes and `Retry-After` are the same; what changes is
how trustworthy the counter is.

**Trigger.** A second replica appears (S-3), or a contractual quota does.

## S-3. Scaling: several workers and replicas

**Why.** A single process hits a CPU or thread-pool ceiling, and online requests start competing with
heavy work.

**Conditions that break.** Rate-limit counters stop being authoritative — either S-2 is needed, or
the limit is divided by N. Everything the process holds in memory (models, caches, pools) is
multiplied by the number of processes. The JWKS cache is duplicated — harmless, but it means N
re-fetches on key rotation.

**Decision.** First several workers in one container, then several replicas behind nginx. Splitting
roles — separate processes for heavy work and for online requests — removes the contention for CPU
and fits naturally with S-1.

**What changes.** Nothing for a caller; in the service's specification the "designed for a single
instance" restriction is lifted and S-2 is introduced.

**Trigger.** The p95 of online operations stops fitting the budget under background load.

## S-4. Direct calls from the browser

**Why.** By default a browser does not reach a Resource Service: the frontend works through an
Orchestration Service. Direct access removes one hop for large uploads and removes the need to
duplicate a resource's CRUD endpoints in the orchestrator.

**Decision.** A CORS whitelist of the frontend's origins with preflight handling; accepting user
tokens alongside s2s ones. The resource's owner is not doubled by this: it is still the `sub` from
the token, it just becomes a user's `sub` instead of a service's. Access by several subjects to one
resource is a separate extension, S-5. Per-IP limits at the perimeter are needed in addition to the
per `client_id`+`sub` ones. CSRF does not arise — the token is in a header, not in a cookie.

**What changes.** A set of allowed origins and preflight appear; error messages have to be fit to
show to a user; the browser is obliged to honour `Retry-After` itself.

**Trigger.** The decision to give the frontend direct access — an edit to the `auth` client registry
in this specification (the frontend's `allowed_audiences`), not a local decision of a service.

## S-5. Local grants on a resource

**Why.** The owner-only rule does not cover "give access to another subject", "give access to an
Orchestration Service on behalf of a user", or "transfer ownership".

**Decision.** A grants table `(resource, subject, right)` in the service's database and a check of
"owner **or** a matching grant"; rights come from a fixed set; the global `roles` from the token take
part as a separate source of permission (a policy in terms of `roles`, as the authorization section
requires).

**What changes.** Operations to issue and revoke a grant appear; the "someone else's → 404" policy
survives only for subjects without a grant.

**Trigger.** The first scenario with two subjects on one resource.

## S-6. Introducing an ORM

**Why.** While a service has two or three entities without object graphs and without invariants over
collections, repositories assemble objects from rows by hand, and that is cheaper than an ORM. The
picture changes once a real aggregate with an object graph appears, or once there are so many
relations that manual mapping takes up a noticeable share of the infrastructure code: then the
identity map, change tracking and cascading persistence of an aggregate start to pay for themselves.

**Decision.** SQLAlchemy ORM with **imperative mapping** (`registry.map_imperatively`): the domain
classes stay the service's own, the mapping description lives in the infrastructure layer, and
neither the direction of dependencies nor the `import-linter` contract is violated. Repositories move
to a session, the Unit of Work is implemented on top of it instead of a Core transaction, and Alembic
keeps working with the same `MetaData`. The declarative style (domain classes inheriting from `Base`)
is not considered — it drags persistence into `domain/`.

**What changes.** Entities become mutable: imperative mapping does not map frozen classes (value
objects stay frozen). Session lifetime becomes an explicit concept — a session per request and
mandatory eager loading, or lazy attributes will fire outside it. Atomic counter increments stay in
SQL: an ORM does not replace them.

**Trigger.** An aggregate with an object graph appears, or the number of related entities grows to
the point where manual mapping becomes the repositories' main work.

## S-7. Moving to a platform-wide event architecture (outside the current scope)

The rule in force is "synchronous over HTTP, no event integration". The condition for revisiting it:
a single domain fact acquires a third consumer (realistically, with the arrival of a PMS with OTA
webhooks and a notification service), or the load becomes peaky and there is nothing to absorb it
with except 429.

What gets introduced:

- **A RabbitMQ broker as a platform component** on the `backbone` network (the shared compose
  project, next to nginx), not inside a service; vhost `/holahost`, one user per service,
  credentials in SM.
- **An event is a fact, not a command**: `booking.created`, `document.indexed`. A topic exchange per
  domain, routing key `<domain>.<event>`; the queue is declared by the **subscriber**, and the
  publisher knows nothing about subscribers.
- **Guarantees**: quorum queues, persistent messages, publisher confirms, manual ack; at-least-once
  ⇒ idempotency is mandatory for every subscriber, and ordering is not guaranteed.
- **Publishing goes through an outbox** in the publisher's database: the event and the state change
  are written in one transaction, and a publisher process drains the outbox.
- **Retries** are TTL buckets with dead-lettering back into the queue; exhausted attempts → the
  subscriber's DLQ.
- **Tracing**: `X-Request-ID` is put into the message's `correlation_id` and restored by the
  subscriber — end-to-end tracing does not break at the queue boundary.
- **The event contract** is versioned and lives in the publisher's git; a breaking change means a new
  routing key.

Everything that needs an answer for the caller stays synchronous HTTP (token validation, search,
generation, reading a resource). Only notifications of a fact and deferred work are replaced by
events.

The price: a second integration model in every service (an AMQP client next to HTTP), operating the
broker (volume, watermarks, monitoring queue depth and DLQs), and mandatory idempotency. On a single
EC2 instance a broker gives no HA — it goes down with everything else, but it becomes a point of
failure at platform scale.

# Authentication and authorization — Authorization Service (`auth`)

`auth` is the platform's **Authorization Service**: the JWT issuer and the single point of
authentication (AuthN) and of **basic authorization** (issuing `aud` from an allowlist plus the
global `roles`) — for users and for s2s alike. It holds user identities and their global rights
(`roles`). Fine-grained authorization — rights over specific resources — sits in the Resource Service
(see persistence).

## Concepts

- **Authentication (AuthN)** — the event "entered credentials, proved identity".
- **Session** — the state "authentication has happened", kept in auth so that it need not be proven
  again (SSO, re-login without a password); an opaque id in an httpOnly cookie, checked only in auth
  (`/authorize`), never in resource services.
- **Access token** — a bearer credential (delegated authorization) with a short TTL; validated
  offline by signature, and valid until `exp`.
- **Refresh token** — a long-lived credential for obtaining a new access token without logging in
  again; stored and rotated in auth, revoked through `/logout`.
- **Authorization code** — a single-use, short-lived code from `/authorize`, exchanged for tokens at
  `/token` (it ties the browser redirect to the exchange).
- **Client** — the calling application: **public** (the frontend, PKCE, no secret) or
  **confidential** (a service, `client_secret`); its identity is the `client_id` claim.
- **AuthZ** — authorization: **basic** (in auth: `aud` + global `roles`) and **fine-grained** (in the
  Resource Service: policies over `roles` + local rights).

## Happy path — user authentication

1. The frontend (a public client) prepares PKCE (`code_verifier`/`code_challenge`) and `state`, and
   redirects the browser to `GET /authorize` (through the gateway).
2. auth: no session → the login page → `POST /login` (email + password) → `Set-Cookie` session; a
   valid session → straight through (SSO).
3. auth issues a single-use `code` → `302` back to the frontend.
4. The frontend checks `state` and exchanges `code` + `code_verifier` for tokens:
   `POST /token grant_type=authorization_code` → `access_token` + `refresh_token`.
5. The frontend calls an Orchestration Service with `Bearer access_token`; the `holahost-auth`
   middleware validates the JWT **offline** and authorizes by `roles`.
6. Orchestrator → Resource Service on behalf of the user: **token exchange** (RFC 8693) against auth
   → a narrowed token carrying `act` → the call; the Resource Service validates offline as well.
7. The access token expired → `POST /token grant_type=refresh_token` → a new access token, with no
   repeat login.
8. Logout → `POST /logout` (revokes the refresh token and ends the SSO session); an access token
   already issued lives until its `exp`.

## User authentication — Authorization Code + PKCE

The frontend is a **public client** and holds no secret: Authorization Code (RFC 6749 §4.1) + PKCE
(RFC 7636). The password is entered on the auth side (an internal login endpoint, outside OAuth —
RFC 6749 §3.1) and never appears in a grant body. Renewal is the Refresh Token grant (RFC 6749 §6);
logout is `POST /logout` (the counterpart of `/login`: RFC 7009 refresh revocation plus ending the
SSO session).

```
GET  /authorize                       # OAuth authorization endpoint (browser-facing, public)
     ? response_type=code, client_id, redirect_uri=<from the client's allowlist>,
       code_challenge=BASE64URL(SHA256(verifier)), code_challenge_method=S256,
       audience=[...], state=<csrf>
     → no session → auth's login page;  a valid session → a code straight away (SSO)
     ← 302 redirect_uri?code=<code>&state=<state>
            # code <=60s, single-use, bound to client_id+redirect_uri+challenge+sub+aud

# Login is an internal auth endpoint (outside OAuth; RFC 6749 §3.1: how the resource owner is
# authenticated is not standardised). This is where the password is checked and a session created.
POST   /login                         # {email, password} -> 200 + Set-Cookie session | 401
POST   /logout                        # counterpart of /login: {refresh_token}+cookie -> revoke refresh (RFC 7009) + end of the SSO session

POST /token   grant_type=authorization_code
     → {code, code_verifier, client_id, redirect_uri}
     ← 200 {access_token, refresh_token, token_type:"Bearer", expires_at}
     ← 400 invalid_grant              # code expired or already used / verifier did not match

POST /token   grant_type=refresh_token          # renewal, with refresh rotation
     → {refresh_token, client_id}
     ← 200 {access_token, refresh_token, expires_at}
```

The access token's TTL is a server-side policy per client, not something the client asks for.

## Identity management

Signup and password change also go frontend → auth directly; the password is entered on the auth
side and an Orchestration Service never sees it. The old password is verified by **auth**.

```
POST   /identities                    # signup
       → {email, password}
       ← 201 {id, email, status, created_at} | 409 email already taken
PATCH  /identities/{id}
       → {status: "active" | "blocked"}          ← 200
PUT    /identities/{id}/password
       → {old_password, new_password}             ← 204 | 401 the old one did not match
DELETE /identities/{id}
       ← 204                          # hard delete, idempotent
```

## S2S — as the service itself, and on behalf of a user

```
POST /token   grant_type=client_credentials                   # RFC 6749 §4.4, as-itself
     Authorization: Basic base64(client_id:client_secret)     # confidential client
     → {audience: [target]}
     ← 200 {access_token, expires_at}     # a service token; cache until ~exp
     ← 401 wrong client credentials + WWW-Authenticate
     ← 403 audience outside the allowlist

POST /token   grant_type=urn:ietf:params:oauth:grant-type:token-exchange   # RFC 8693, on-behalf-of-user
     Authorization: Basic base64(client_id:client_secret)
     → {subject_token: <the incoming user access_token>, audience: <downstream>}
     ← 200 {access_token, expires_at}     # the user's sub is kept, aud is narrowed, act is added
     ← 403 audience outside the allowlist
```

**On the token exchange:** it is called **in the hot path** on every on-behalf-of-user hop, so auth
becomes availability-critical for cross-service user flows — accepted deliberately. A
client_credentials token, by contrast, is fetched once and cached until roughly its `exp`.

## JWKS

```
GET /.well-known/jwks.json            # no auth, Cache-Control: max-age=300
```

Client authentication at `/token`: **public** — PKCE, no secret; **confidential** (s2s) —
`Authorization: Basic base64(client_id:client_secret)`. Errors use `{error: {code, message}}`. The
order at `/token`, failing fast: authenticate the client → the grant-specific check (code + verifier
/ refresh / subject_token) → the identity's status → the client's audience allowlist → **mint**, the
signature being the final act.

## Claims (an RFC 9068 profile plus `act` from RFC 8693)

One `holahost-auth` middleware validates all three kinds of token. The discriminator: `sub ==
client_id` ⇒ a service token, with no user context; otherwise a user token. The presence of `act` ⇒
delegated.

| claim | user token | service token (client_credentials) | exchanged (token exchange) |
|---|---|---|---|
| `iss` | auth | auth | auth |
| `sub` | the user's uuid | = the service's `client_id` | the user's uuid |
| `client_id` | the frontend's public client | the calling service | the service that requested the exchange |
| `aud` | the services in the chain (allowlist) | the target service | downstream (narrowed) |
| `roles` | global (**required**) | — | inherited from the user |
| `act` | — | — | `{ sub: the calling service }`, nested on multi-hop |
| `exp, iat, jti` | auth; `kid` and `alg` (RS256/ES256) in the header | | |

`scope` is not used — policies over `roles` are the Resource Service's business. `product` has been
replaced by `client_id`.

## Where rights and clients are stored

- **Users**: identities plus global `roles` (an extensible list) — in the **auth database**.
- **s2s clients**: a registry in **git config** (the set of services is fixed; git holds only
  `secret_hash`, while the secret values live in SM).

```yaml
# auth's git config
clients:
  web-guest-portal:            # public (the frontend)
    type: public
    pkce: required             # S256
    redirect_uris: ["https://app.holahost.com/callback"]
    allowed_audiences: ["rag-documents", "pms-api"]
    access_token_ttl: 900
    refresh_token_ttl: 1209600
    refresh_rotation: true
  chat-assistant-api:          # confidential (s2s)
    type: confidential
    secret_hash: "$argon2id$..."
    allowed_audiences: ["rag-documents"]
  guest-reply-cli:             # confidential (console orchestrator, holahost/tools/guest-reply)
    type: confidential
    secret_hash: "$argon2id$..."
    allowed_audiences: ["rag-documents", "llm-client"]
```

## auth is product-agnostic (sessions)

auth owns user sessions **without knowing the product's business logic**:
- it stores only the global identity (email / password / `roles`), never a user's product data; the
  **join key is `sub`**, and the product profile lives in the Resource Service;
- it can only block an identity **globally**; "block in this particular product" is a Resource
  Service rule.

## Revoking access

Inbound JWT validation is offline, so `PATCH status:blocked`, `DELETE` and `POST /logout` affect only
**new** tokens and mints; an access token already issued lives until its `exp`. There is no
revocation list — the maximum revocation lag equals the cap on the access TTL, which is why that TTL
is kept short. Token exchange goes through auth in the hot path, so for delegated hops auth can
refuse the exchange at the next hop, but a token already exchanged lives until its `exp`.

**Logout** is `POST /logout`, the counterpart of `/login`: it revokes the application's refresh token
(RFC 7009) **and** ends the SSO session in auth (otherwise `/authorize` will not ask for the password
again). An access token already issued lives until its `exp`.

**The frontend's contract on logout.** The frontend must:
1. call `POST /logout` (`{refresh_token}` plus the session cookie); the session cookie is cleared by
   **the server itself** through `Set-Cookie … Max-Age=0` — it is httpOnly and JS does not touch it;
2. **clear local state — always, even if the request failed:** drop `access_token` and
   `refresh_token` from memory and storage, reset the in-memory auth context (profile, `roles`), and
   erase the transient `code_verifier` and `state`. Otherwise the remaining access token keeps
   working until its `exp` — offline validation will not revoke it;
3. stop the background silent-refresh timer, so that it does not fetch tokens again after logout;
4. put the UI into its logged-out state (redirect to login or to the landing page);
5. *(desirable)* notify the SPA's other tabs (BroadcastChannel or a `storage` event) for a
   synchronous logout.

Do the local cleanup in step 2 **before, and independently of,** the server's answer; logout is
idempotent. Where possible keep tokens in memory rather than in `localStorage`, which lowers the risk
of exfiltration through XSS.

# Shared infrastructure

The shared infrastructure is one platform Terraform root (`holahost/infra/`), applied against a
workspace per environment. A workspace here and a **directory per environment** in a service's roots
(see "Brief: a microservice's infrastructure and CI/CD") are not an inconsistency but two different
problems: the platform root describes one and the same set of resources with different values, where
a workspace is exactly right; for a service, both the set of resources and the rights over them
depend on the environment.

- Compute: EC2 + EIP + instance role (ECR pull, SM read, CloudWatch)
- Network: a security group — 80 open (the origin is authenticated by the `x-origin-secret` header
  the API Gateway adds), 22 closed, access to the instance through SSM
- CDN: CloudFront — the default behavior → S3 (the frontend); the `/api/*` behavior → API Gateway
  (caching off, `Authorization` passed through)
- Codebase: a GitHub repository (this one)
- Domain: Route 53 + ACM
- Storage: an S3 frontend bucket
- AWS API Gateway (HTTP API): a single catch-all route `ANY /api/{proxy+}`, gateway-wide throttling
  (the global edge limit — layer 1 of rate limiting), an HTTP integration → `http://<EIP>/{proxy}`
  plus parameter mapping with the static `x-origin-secret` header
- SSM Parameters: exports for the service stacks — instance id, ECR registry, ids and names of shared
  resources
- IAM for CI/CD: a GitHub OIDC provider registered in the account (trusting
  `token.actions.githubusercontent.com`) and one role per service and environment for its pipeline
  (least privilege: push to its own ECR repository, `ssm:SendCommand`/`GetParameter` against its own
  instance, apply of its own Terraform roots)

On the EC2 instance, bootstrapped through cloud-init:
- Docker plus `docker network create backbone`
- The platform compose project — a single container: nginx with a static, generic config (dynamic
  `$svc` resolution through Docker DNS, the `x-origin-secret` check, port 80, per-IP `limit_req` as
  pre-auth flood protection — layer 2 of rate limiting, and adding `X-Request-ID`)

## Environments

### dev (local)

A local stack of all the microservices, without the frontend. Conceptually:

1. Once: `docker network create backbone`.
2. Bring up the platform compose project locally: the same nginx config, with `x-origin-secret` set
   to a known dev value; the entry point is `http://localhost/<svc>/…`.
3. For each service: `docker compose -f services/<svc>/docker-compose.yml up -d` — the image is built
   locally (`build:`), configuration and secrets come from `.env.dev`, and dependencies (database,
   cache) are containers inside the service's own compose project.
4. auth comes up as an ordinary service; its dev JWT signing keys live in its `.env.dev`, and the
   other services validate tokens with the dev key. Until `auth` is built, tokens are minted by the
   `infra/scripts/mint-dev-token.py` script with the same key, which also publishes JWKS; to the
   services the source of the token is transparent.
5. Check: `curl -H "x-origin-secret: <dev>" http://localhost/<svc>/health`.
6. The whole stack: the `infra/scripts/dev-up.sh` script iterates over `services/*` and performs
   step 3.

### staging (terraform)

1. The platform, once: `terraform workspace select staging && terraform apply` in `holahost/infra/` —
   EC2, the gateway, CloudFront, and the environment's SSM parameters.
2. The service's infrastructure, once: `terraform -chdir=<svc>/infra/common apply`, then
   `terraform -chdir=<svc>/infra/envs/staging apply` — ECR, SM secrets, observability; then fill in
   the secret values in SM. No `workspace select` here: for a service the environment is chosen by
   the directory.
3. Deployment is the service's own CI/CD pipeline.

### prod (terraform)

Identical to staging (the platform root uses the `prod` workspace; the service uses
`infra/envs/prod/`). The differences:
- a prod deployment happens only after a successful smoke check on staging;
- CI has a manual approval gate before the prod step.

# Adding a new microservice (Resource / Orchestration Service)

A microservice's whole codebase is kept in isolation under `services/<svc>/`: the code, the
Dockerfile, `docker-compose.yml`, `.env.dev.example`, CI/CD and OpenAPI.

## Preliminary design of a new microservice

Before building a microservice, agree its preliminary design decisions and extend this specification
with:

- the happy-path flow at the level of the system architecture's components — as a check on the
  topology and on how the microservices interact
- Domain Entities
- DB Schema
- API Contracts
- Observability (the microservice's main technical metrics)

- Authentication and authorization, the Tech Constraints Doc, Infrastructure and CI/CD — update the
  corresponding sections of this specification if the microservice's design decisions affect the
  shared stack or the briefs below.
- Reuse — check the design against "Reusable shared entities": what already exists there is used,
  not re-implemented; a piece that is the same for any service and would break silently as a
  per-service copy is extracted (a library, the service template, a Terraform module, a CI
  action) — as a placeholder until the first development that needs it; the domain layer stays
  the service's own (see "What is deliberately not extracted").

## Individual conditions for designing a microservice

### Brief: a microservice's persistence storage

Every Resource / Orchestration Service stores the rights over its own resources itself — policies in
terms of the global `roles` from the token, plus local grants. The global `roles` and the user
identities are held by auth (see "Authentication").

### Brief: authorization and proof of authentication

The procedure for proving authentication and authorization, in principle:

A service mounts the `holahost-auth` middleware on every route except `GET <API_BASE_URL>/health`.
On **every** request the middleware does the following — the service trusts neither the frontend nor
the gateway, and the check is entirely on the service's side:

1. Take the `Authorization` header. Absent, or not of the form `Bearer <token>` → **401**.
2. Parse the JWT (three base64url segments). Does not parse → **401**.
3. Check the token header's `alg`: only the expected one (RS256/ES256); `none` and HS* → **401**.
   This is protection against algorithm substitution; the expected algorithm is fixed in the
   middleware's config and is never read out of the token.
4. Verify the signature with the public key for the `kid`, taken from the JWKS cache. An unknown
   `kid` → a single JWKS re-fetch, to cover key rotation; if it is still unknown, or the signature is
   invalid → **401**.
5. Check the standard claims: `exp` (with a clock-skew allowance of at most 30 s), `iat`, `iss` =
   Holahost's auth, `aud` = the expected audience. Any of them off → **401**.
6. On success, put `sub`, `client_id`, `roles` and, if present, `act` into the context. The endpoint
   then checks authorization: the `roles` from the token plus local rights over the resource → not
   enough → **403**. For delegated tokens, which carry `act`, the endpoint also checks the calling
   service (`act.sub`) where that matters — protection against a confused deputy.

A 401 response carries no reason in its body, so as not to help an attacker enumerate; the reason
goes to the log. A 403 means only "the token is valid, the rights are not there" — the 401/403
discipline is a contract with the frontend's interceptor. Inbound validation is offline: it makes no
calls to auth or its database, and a network call is permitted only in step 4, on key rotation.
**The exception is outgoing on-behalf-of-user calls:** before calling downstream, a service performs
a token exchange against auth (RFC 8693) — a deliberate hot-path dependency on auth (see
"Authentication").

**Services without authorization (public)**

- The middleware is not mounted; the `Authorization` header is ignored and there is no user context.
- All input is untrusted; protection from abuse is the gateway-wide throttling on the API Gateway,
  with the service's own limits inside it where needed.
- The service's OpenAPI states it explicitly: `security: []`.

### Brief: rate limiting

Between services there is neither a dedicated service nor shared storage: one instance per service ⇒
the counters live in process memory (an in-memory token bucket or fixed window).

Beyond the gateway-wide throttling and nginx's per-IP `limit_req`, provide for a **per-service
inbound** limit: middleware immediately after `holahost-auth`, keyed by `client_id`+`sub` from the
token (the calling service × the end user). Public services, which have no auth, are keyed by IP
(`X-Forwarded-For` from the gateway). Exceeding the limit → **429 + `Retry-After`**, the same
contract as at `/token`.

The middleware order on a request: `holahost-auth` (401/403) → rate limit (429) → handler (403).

**The caller's discipline:** on a 429, honestly wait out the `Retry-After` with backoff;
inter-service HTTP calls carry a timeout and a retry limit, so that a slow or limited dependency does
not amplify the load — the equivalent of backpressure when the integration is synchronous HTTP with
no events.

**Limitation:** once a service is scaled to N replicas the in-memory counter stops being
authoritative — then either shared storage, or the limit divided by N, and the choice documented.

Configuration, per service:

```yaml
rate_limits:                             # a fixed one-hour window, no burst
  user:    { ingest: 60,  read: 600 }    # per client_id+sub pair (an exchanged token)
  service: { ingest: 60,  read: 600 }    # per client_id (a service token, sub == client_id)
```

The window is fixed and hourly. `burst` is not introduced, because there is no separate burst
mechanism — there is one counter per window.

There is deliberately no single `per_client` ceiling either. It would stand in for a dimension the
record does not have: a service token's `sub` equals its `client_id`, so its counter is an aggregate
over the whole integration, while an exchanged token's counter is per user of that integration. One
number for both cases either throttles a busy integration or hands every one of its users the whole
integration's quota, and case-by-case exceptions per `client_id` only treat the symptom. Splitting by
the kind of token settles this by construction; personal per-client ceilings remain an extension for
later, once there is data (see the `stage_ms` / `top_score` instrumentation).

### Brief: limiting the request body size

The division of responsibility is the same as in the other briefs: the platform implements it, the
service mounts it and declares its own value.

**The platform implements.** A shared ASGI limiter in `holahost-http`, parameterised by a single
number:

- exceeding the cap by `Content-Length` is refused **without reading the body**;
- under `Transfer-Encoding: chunked`, where there is no such header, the bytes are counted as they
  stream and reception is cut off on exceeding the cap — otherwise the check is bypassed simply by a
  client not sending the header;
- the refusal is a `413` in the shared error envelope, with the ceiling in `details`.

**The service uses it.** It mounts the middleware and declares its own value alongside its other
limits, deriving it from its own file limit (`body_cap_for_upload`): the middleware measures the
whole body including the multipart framing, so a ceiling equal to the bare file limit rejects an
upload of exactly the permitted size.

**The contract is that there is exactly one point of control: the middleware.** Mounted with a value
declared — the limit exists; not mounted — there is no limit. No second line of defence and no
"don't rely on the gateway as the only barrier": a barrier with two owners is a barrier with no
owner, and dev and prod must behave identically by construction rather than by agreement.

This is about the **size of the request body**. A service's own check over the extracted file is a
domain limit, not a second transport barrier: it measures a different object, answers with its own
error, and advertises the same ceiling (`reported_limit`) so that a caller is never given two
different numbers.

**Why this is middleware and not a check in the handler.** The framework parses the request body
while assembling the handler's arguments — that is, **before** it resolves the handler's
dependencies. Any check written as a dependency fires only after the upload has been accepted in
full.

### Brief: the rate limit as middleware

This complements "Brief: rate limiting" above, which describes *what* is counted; here it is *where*
the check sits and how it is divided between the platform and the service.

**The platform implements.** Shared middleware in `holahost-http` that checks the limit **before the
body is parsed**:

- the key is `client_id`+`sub` from the token, and the kind of identity comes from
  `TokenContext.is_service_token` (`sub == client_id` for a service token), so the ceiling is chosen
  by the pair "bucket × kind of identity";
- the refusal is a `429` with `Retry-After` in the shared error envelope;
- the in-memory counter implementation has **bounded memory**: the key is built from the caller's
  identity, so an unbounded map grows with the number of callers ever seen and never shrinks — the
  window expiring overwrites a key but does not remove it. What is needed is boundedness by
  construction (an LRU with a ceiling), not a cleanup timer.

**The service uses it.** It mounts the middleware and declares its buckets, the mapping from routes
to buckets, and the ceilings per kind of identity; it also chooses the counter implementation.
Buckets are split by the **cost of the operation**, not by HTTP method.

**The contract is the same:** exactly one point of control, the middleware. The caveat about N
replicas — the in-memory counter ceasing to be authoritative — applies to the counter
implementation, not to the contract.

**Why before the body is parsed.** As a dependency, the check fires after the framework has already
read the body: a caller that has exhausted its quota still manages to upload the whole file before
hearing `429`.

### Brief: domain exceptions

**The service declares.** One type for every invariant violation in `domain/`, in its own
`domain/exceptions.py`: `DomainValidationError(ValueError)` with `field: str | None`. It is not
extracted into a library, for the same reason as the base classes for value objects and entities.
The service template ships it instead — a copy the service owns — already listed in
`SILENT_500_TYPES` and with the tests of both: a service that declares the type and forgets to list
it answers a defect with a traceback outside the JSON log, and nothing fails.

**What `field` says** is read, not assumed:

- **set** — the violation traces back to a request field. The use case that knows which one
  translates it into a published application error (`InvalidPayloadError` or one of the service's
  own) and names the field from `field` rather than re-deriving it;
- **`None`** — nothing the caller sent could have caused it: a defect. Nothing translates it; the
  interface lists the type in `create_edge_app(silent_500_types=...)`, and it is answered
  `500 InternalError` with an empty body.

**The contract.** A subclass is added only when one call can raise the type for more than one reason
and the caller has to select one of them: selecting on a `field` string is a comparison no type
checker sees. The type is not a `PlatformError` — the domain knows nothing of HTTP, and a published
identity belongs to the application layer's errors. Its message is server-side only: it reaches the
log, never a response body.

**Why a named type rather than a bare `ValueError`.** An exception nothing handles reaches the
bare-`Exception` handler, which re-raises after writing the response, and uvicorn prints a traceback
outside the JSON log and its scrubbing. Registering the handler for `ValueError` itself would catch
far more than the domain — Pydantic's `ValidationError` is a `ValueError` too.

### Brief: a microservice's infrastructure and CI/CD

Every service (Authorization / Resource / Orchestration) is a **self-contained deploy unit**. It has
to provide for:

- **its own CI/CD pipelines** for the **staging / prod** environments and validation in **local
  dev** (validation plus rollout) — specified in the service's own document;
- **its own set of infrastructure resources**: its own **ECR repository**, secrets, observability and
  its own Terraform roots — a **directory per environment** (`infra/envs/<env>/`), not a workspace.
  Prescribing both at once is not possible, and the implementation went with directories. Different
  environments differ not only in variable values, which a workspace covers, but in the set of
  resources and in the rights over them; a separate root makes that visible in the file tree rather
  than derivable from whichever workspace was selected last. The price is duplication between
  `staging/` and `prod/`, and it is accepted deliberately;
- the service name `<svc>`: the container name on the `backbone` network, the path segment
  (`API_BASE_URL = /api/<svc>` — a bare path with no domain), and the ECR repository name;
- the container listens on port 8080 (fixed by convention, never published outside);
- JWT validation inside the service, offline by signature (the `holahost-auth` middleware; see
  "Authentication");
- `GET <API_BASE_URL>/health` for the smoke check. Under the service's base path like every other
  route: the gateway routes by prefix and does not rewrite the path, so a route published at a bare
  `/health` is unreachable from outside and the smoke check never gets to it;
- compose: `networks: [backbone]` (external), `restart: unless-stopped`;
- an OpenAPI schema;
- **independent deployment**: rolling out one microservice touches neither the other microservices
  nor the shared infrastructure:

  1. `terraform apply` of the service's roots (ECR, secrets, observability).
  2. CI: push the image → SSM Run Command: the compose project in `/opt/services/<svc>/`,
     `docker compose up -d`.
  3. Smoke: `curl https://<domain>/api/<svc>/health`.

#### A service's infrastructure — the defaults

Below is what holds for **any** microservice without a decision of its own. A service's
specification describes only its deviations from and additions to this list; there is no need to
repeat the defaults in it.

**Environments:** `dev` (local development), `staging` (checking the rollout and the smoke test
before prod), `prod`.

**dev.** The service's own compose project: the application container, built from `build:`, plus its
dependencies as containers. The `backbone` network is external and created once. There is no platform
nginx and no gateway on dev: the application's port is published on the host, callers reach it
directly, and the caller sets `X-Request-ID` itself. Configuration comes from `.env.dev`, a copy of
the versioned `.env.dev.example`; `.env.dev` itself never reaches git. Migrations are applied by a
separate Makefile target before the first start.

**Provisioning.** A service's infrastructure is described by its own Terraform roots, **one directory
per environment** (`infra/envs/<env>/`), not a workspace:

| Root | What it creates | When it is applied |
|---|---|---|
| `infra/common` | the service's ECR repository with a lifecycle policy | once, one for all environments |
| `infra/envs/<env>` | the service's secrets in SM (with empty values), the log group, the alarms | once per environment, before the first rollout |

State lives in an S3 bucket in the platform account, with locking; the bucket and the lock table are
created once outside Terraform — the bootstrap exception to the rule that everything which is not
one-off is described in Terraform. Editing resources by hand in the console is not allowed: the
divergence is found by the next `plan` and is treated as an incident. Terraform does not create the
application or its dependencies — they appear as containers when the compose project is rolled out to
`/opt/services/<svc>/` through an SSM Run Command.

**Secrets.**

| Environment | Where they live | Who reads them | Rotation |
|---|---|---|---|
| dev | `.env.dev` on the developer's machine | the application process | not required; the values are known not to be real |
| staging / prod | AWS Secrets Manager, the resources created by the service's TF root | the container at startup, through the instance role, which has SM read | replacing the value in SM plus a container restart — but only for secrets the service merely **presents** (see below) |

The values are filled in by hand once after `terraform apply`; only the secrets' names reach git and
the tfstate. Secrets are not baked into the image and are not written into the compose file's
variables.

**Rotation: a restart is not always enough.** It changes only what the process *presents*. If a
secret has a second side holding a copy of it — a database role's password, a key at an external
provider — then restarting with the new value runs into the old one and brings down every connection.
Such a secret needs a deploy step that brings the second side into line (for a database,
`ALTER ROLE … PASSWORD`), and its rotation completes on the **next rollout**, not on a restart. The
distinction has to be explicit in the service's runbook: for each secret, "restart" or "rollout".

**Environment runbook.** A `docs/runbook.md` document in the service's repository, with a section per
environment name. Each section answers four questions, and the answers have to be executable by
copy-paste:

1. **Deploy from scratch** — from an empty environment to one answering `GET <API_BASE_URL>/health`:
   applying the TF roots, filling in the secrets, the first rollout, the migrations.
2. **Check** — the `GET <API_BASE_URL>/health` smoke test plus a check of the service's profile
   operation; where to look at the logs.
3. **Update** — rolling out a new version and the order in which migrations are applied (migrations
   before code).
4. **Roll back** — returning to the previous image, and what to do about a migration already applied.

For dev, additionally: how to bring the stack up with one command, how to recreate the dependencies
from scratch, and how to get a token (until `auth` is built, from the dev minter).

#### Applying infrastructure — by hand

A service's Terraform roots (`infra/common`, `infra/envs/<env>`) are applied by an operator by hand
(`terraform apply` with valid AWS credentials); a pipeline is not required for this. The OIDC role
from the point above is needed only when a service wants automatic deployment through CI/CD
(`<svc>-deploy-staging` / `<svc>-promote-prod`); until it exists, `terraform apply` by hand is the
normal way to bring a service up, not a temporary workaround.

#### CI/CD and conventions — the defaults

These hold for any microservice; a service's specification describes only its deviations.

**Branches and commits.** GitFlow: the long-lived `main` and `develop`. Short-lived branches are
`feature|bugfix|refactor|chore|docs|test/[<service>/]<slug>`, taken from `develop` and merged back
into `develop`; `release/v*` and `hotfix/v*` go into `main` with a back-merge. A branch developing a
microservice carries its name as a segment. Commits follow Conventional Commits, with a type from
`feat|fix|chore|refactor|docs|test|build|ci`. Versioning is **per component**: a
`<component>/vYYYYMMDD.N` tag on the commit of the `release/v*` branch that passed staging, which is
also the trigger of the prod pipeline. The branch is then merged into `main` as usual.

The tag goes on the release branch's commit rather than on the merge commit in `main`, and that
follows from squash merging: a squash produces a new commit object with a new sha that never existed
on any `release/*`. The promotion addresses the image by the tagged commit's `git-<sha>` — the only
binding of "this image passed staging", because `deploy-staging` builds only `release/v*` commits. A
tag on the merge commit would point at a sha for which no image exists, and the promotion would find
nothing.

Naming conventions (Python, database, migrations) are in `CONTRIBUTING.md` at the repository root.

**Static analysis.** `ruff` (lint + format, `target-version = "py312"`, `line-length = 100`, rules
`E,F,W,I,UP,B,SIM,RUF,S`), `mypy --strict` with the Pydantic plugin, and the `import-linter` contract
(`layers = ["interface","infrastructure","application","domain"]`, `config` a leaf, `scripts` outside
the contract). Every rule is on from the first commit: the codebase is new, so no baseline strategy
is needed.

**Pre-commit.** The hooks live in the shared `.pre-commit-config.yaml` at the repository root:
`ruff check --fix` and `ruff format`, `mypy`, `lint-imports`, `conventional-pre-commit` at the
`commit-msg` stage, `gitleaks`, and the basic checks (whitespace, EOF, YAML, JSON, merge-conflict,
`check-added-large-files`). Bypassing them with `--no-verify` is forbidden by policy; CI runs the
same checks and blocks the PR.

Locally the Python hooks walk every package in the repository, so a library change is checked
against every service that depends on it before the push. A pipeline gates only its own package: the
generic hooks over its changed files, and `ruff`, `mypy` and `lint-imports` check-only on that
package. Walking every package from a pipeline would make it install every other package's
environment and block a PR on code it does not own.

**Pipelines.** GitHub Actions starts from the root `.github/workflows/`, which holds **thin trigger
stubs** `<svc>-*.yml` with a path filter of `holahost/services/<svc>/**` plus `holahost/libs/**`;
the logic lives inside the service. The libraries are matched because a service runs on their code:
a library change re-runs the pipeline of every service, and that run is what checks the dependents
against it. Every library is matched, not a list of today's dependencies — an extra run costs
minutes, while a dependency added without updating the list breaks a service on `develop` unnoticed.
The diff base of a new branch's first push is its merge-base with `develop`: a diff from the root
commit matches every filter. A job skipped by the filter must report success into its required
context, or the PR will hang.

| Pipeline | Trigger | Steps |
|---|---|---|
| `<svc>-ci` | a PR into `develop` / `main` / `release/*`, a push to a short-lived branch | `pre-commit` → the Python gates of the service's package → tests → `docker build` without a push → `terraform plan` of the service's roots |
| `libs-ci` | the same, with a path filter of `holahost/libs/**` | `pre-commit` → each library's Python gates → its unit tests |
| `<svc>-deploy-staging` | a push to `release/v*` | `terraform apply` → `docker build` and push to ECR under the `git-<sha>` tag (that one only — see "Image tags" below), remembering the digest → SSM Run Command: `alembic upgrade head`, then provisioning the application role, then `docker compose up -d` → smoke |
| `<svc>-promote-prod` | a push of a `<svc>/v*` tag | `terraform apply` → resolve the digest by the tagged commit's `git-<sha>` **without rebuilding** → SSM Run Command: migrations, then provisioning the application role, then rolling out that same digest → smoke → an `environment: prod` gate with manual approval → tagging the rolled-out digest `release-v<version>` |

**Image tags.** A service's ECR repository is immutable (`IMMUTABLE`, the only exception being
`latest*`), so no tag can be written twice, and each tag is written exactly once by its own pipeline:

- `git-<sha>` is written by `deploy-staging`, once per commit. It is idempotent: if the tag is
  already in the repository the image is not rebuilt and the existing digest is reused. That makes it
  safe to re-run a workflow that failed after the build — a flaky migration, a smoke-check timeout.
- `release-v<version>` is written by `promote-prod`, once per version, **after** a successful smoke
  test on prod, onto the very digest that was rolled out. The tag means "this build shipped to prod",
  not "this build was built at some point".

The version tag is deliberately not applied by the staging build: `release/v*` is a branch, not a
commit, and stabilisation commits on it produce several builds for one version. A tag derived from
the branch name cannot be overwritten by a second such push — the pipeline would fail at
`docker push` — and one derived from the version would not answer which of the builds was verified.
The promotion therefore addresses the image by the tagged commit's `git-<sha>`: a git tag points at
exactly one commit, and its image is the one that passed staging. A tag on a commit that
`deploy-staging` never built stops the pipeline immediately.

Authentication against AWS is GitHub OIDC with a role per service and environment, least privilege;
there are no long-lived keys. The local equivalent is `make ci-local` (hooks plus tests) before a
push.

**Rollout strategy — recreate.** `docker compose up -d` stops the old container and brings up a new
one: a window of unavailability measured in seconds is accepted, and blue-green or rolling
deployments make no sense on a single instance. The order is mandatory: migrations are applied
**before** the new container comes up, which is why they have to be backwards-compatible — a breaking
change is split across two releases. A rollback is a rollout of the previous digest; if a migration
is irreversible, the data is rolled back by restoring the database, not by `downgrade`.

**Repository.** The default branch is `develop`. Branch protection on `main` and `develop`: a PR is
mandatory, the required contexts are the CI jobs of the affected components, and direct pushes are
forbidden. Merges are squashes. Head branches are deleted automatically. The PR template is
`.github/PULL_REQUEST_TEMPLATE.md`, in English — the repository is public.

# Repository structure

A monorepo:

- `holahost/frontend/` — Holahost's web frontend.
- `holahost/docs/` — Holahost's design documents, this file among them. The public documentation is
  the `README.md` files.
- `holahost/infra/` — the application's **shared infrastructure** (domain, frontend hosting, the
  gateway, GitHub settings, the dev-stack scripts), plus `modules/` — the reusable Terraform modules
  that the services' Terraform roots call.
- `holahost/services/<svc>/` — the microservices.
- `holahost/libs/<lib>/` — the platform's shared libraries (`holahost-observability`,
  `holahost-http`, `holahost-auth`, `holahost-db`); consumed by services as path dependencies and
  never published separately. The dependencies between them run one way: `observability → http →
  auth`, and `db` depends on none of them.
- `holahost/make/common.mk` — the shared make targets, pulled in with `include` from a service's
  `Makefile`.
- `holahost/tools/<tool>/` — the platform's console tools; not deploy units, with no image and no
  ECR, versioned together with the monorepo.
- `holahost/templates/service/` — the template for a new microservice (see below).

# Reusable shared entities

Everything that is the same for any microservice lives in one place and is not rewritten in every
specification. A service's specification **references** such an entity rather than duplicating it.

**The rule for filling this in:** if the content does not exist yet, or needs reworking, only a
placeholder stands here — the name, the place and the purpose. The content appears with the first
piece of development that needed the entity, and from that moment it is mandatory for every
subsequent service.

| Entity | Where it lives | Status |
|---|---|---|
| `holahost-observability` — the JSON logger, the field allowlist mechanism, the core fields of the `op_completed` event, the free-text scrubber | `holahost/libs/holahost-observability/` | implemented |
| `holahost-http` — the HTTP edge: the `{error:{code,message,details}}` envelope and `PlatformError`; the `X-Request-ID`, body-limit and rate-limit middleware; the `RateLimiter` port with an in-memory implementation; **the `create_edge_app` edge factory**, which fixes the middleware order and mounts the routers; the exception handler driven by the service's contract; the platform errors `MalformedRequestError`, `InvalidPayloadError`, `NotFoundError` and the `InternalError` identity; the published schemas for them; the `bearerAuth` declaration | `holahost/libs/holahost-http/` | implemented |
| `holahost-auth` — the offline JWT validation middleware (signature, claims, JWKS cache, the 401/403 discipline), `TokenContext`, the `AuthConfig` config (five token-validation variables, reading the environment itself) | `holahost/libs/holahost-auth/` | implemented |
| `holahost-db` — the storage-failure contract (three types) and the translation of vendor errors, the `UnitOfWork` port and its SQLAlchemy implementation, the engine factory, retrying a transaction on conflict, the two Postgres identities as typed settings, RLS binding and the startup guard, provisioning of the application role, the skeleton of `alembic/env.py` | `holahost/libs/holahost-db/` | implemented |
| The shared make targets (`lint`, `format`, `typecheck`, `test`, `test-int`, `lint-imports`, `openapi`, `dev-*`, `migrate-*`, `ci-local`, `ci-image`, `ci-tf`) | `holahost/make/common.mk`, pulled in with `include` from a service's `Makefile` | implemented |
| The platform's Terraform modules: `service-ecr` (the image repository and its lifecycle policy), `service-observability` (the log group, the SNS topic and its subscription, the filters and the alarm over the `op_completed` core) | `holahost/infra/modules/` | implemented |
| The shared CI composite actions: `setup-python-toolchain`, `build-push-image`, `ssm-migrate-deploy`, `smoke-check`, `terraform-apply` | `.github/actions/` (the repository root — GitHub reads only that) | implemented |
| The service template: the clean-architecture tree, `Dockerfile`, `docker-compose.yml`, `.env.example`, `alembic.ini`, a base `pyproject.toml` (`ruff`, `mypy` strict, the `import-linter` contract, `pytest`), a test skeleton (testcontainers + `alembic upgrade` + provisioning of the unprivileged role, a JWKS server and token minting, registration of the error handlers), the domain exception type already listed in `SILENT_500_TYPES`, and a generated `docs/openapi.json` | `holahost/templates/service/` | implemented; `make test`, `make test-int` and `make openapi-check` pass on the copied tree |
| `holahost-client` — the caller's discipline: obtaining and caching an s2s token, setting `X-Request-ID`, honouring `Retry-After`, parsing the error envelope into exceptions | `holahost/libs/holahost-client/` | placeholder, see below |
| A reusable CI workflow (`workflow_call`) instead of a copy of the pipeline body in every stub | `.github/workflows/` | placeholder, see below |

## What stayed a placeholder, and why exactly these

The rule for filling this in is unchanged: where there is no content, the name, the place and the
purpose stand; the content appears with the first piece of development that needed the entity. Below
are the two cases where a consumer arguably already exists but extracting is premature — a decision,
not an oversight.

**`holahost-client`.** The framework specification requires the caller's discipline, and
`guest-reply` implements it — but there is exactly one consumer. The next one will be built
differently: an Orchestration Service takes its token not from a `client_credentials` cache held
until `exp`, but through a token exchange in the hot path on every on-behalf-of-user hop. So half of
`guest-reply`'s client would not suit it, and the API would have to be broken right after it
appeared. What remains common is `X-Request-ID` and honouring `Retry-After` — a few dozen lines. The
trigger: the first Orchestration Service.

**A reusable CI workflow.** The repeating *steps* are already extracted — those are the composite
actions above. Within the pipeline body, four decisions are service-specific (the path filter's
regex, the image's name and size ceiling, whether there is an `openapi-check`, whether there is an
integration run) out of roughly a dozen steps. Designing a `workflow_call` with four inputs from a
single example is a way to guess the wrong interface and, unlike with Python libraries, nothing here
checks the mistake: a workflow is not typed, and the divergence would surface only at the second
service. The trigger: the second pipeline.

## The operation-completion event contract

A metric on this platform is a structured log event, not a separate metrics system — there is
neither Prometheus nor an agent in the topology. The event's name and the core of its fields are
therefore a **platform contract**, not one service's presentation choice.

```
op_completed { request_id, client_id, sub, route, outcome, duration_ms, error_reason? }
```

- **One event per request**, successful or not, including refusals before routing: those are written
  by `holahost_http.log_rejection`, because middleware answers without entering the handler and such
  a request would otherwise never reach the log at all.
- **A refusal's identity is `outcome`**; there is no separate code field. Every filter matches on it.
- **The level is part of the contract:** `ERROR` on 5xx, `WARNING` on any refusal caused by the
  caller, `INFO` on success and on `startup_completed`. Filters do not read the level — it is for a
  human.
- `error_reason` is the only free-text field. It is filled in only where the response body carries no
  reason (5xx and refusals before routing), and it is scrubbed on the logger's side.
- Beyond the core, a service declares **its own** fields as a list in its `config/logging.py`. A
  field name outside the allowlist fails the call rather than silently shortening the line: the
  allowlist exists precisely so that content — a document's text, a prompt, a token's body — cannot
  end up in the log.

Why one name for all: the CloudWatch filters for 5xx, for authorization refusals and for limit
refusals are derived from it and from the core fields, they live in the `service-observability`
Terraform module, and they are written once. An event name per service would turn one set of filters
into N copies of it.

## The order of the HTTP edge's middleware

```
RequestId → BodySize → Auth → RateLimit → routing
```

The order is load-bearing, not stylistic:

- `RequestId` outermost, or a refusal by any of the following carries no identifier of the caller;
- `BodySize` before everything else, because the framework reads the body while assembling the
  handler's arguments — that is, **before** resolving its dependencies;
- `Auth` is the only thing that puts the token into `scope["state"]`;
- `RateLimit` inside `Auth`, because it keys on that token; if the token is not there,
  `RateLimitMiddleware` raises `RuntimeError` rather than treating the route as unlimited.

**The order is not the service's to choose.** The application is assembled by
`holahost_http.create_edge_app`: the service passes in *what* runs (the authentication middleware,
the limiter, the mapping of routes to buckets, the body ceiling, the error for a missing
`X-Request-ID`, its own routers), and the factory decides the sequence. Written out by hand it is
four lines a reviewer has to check by eye, and the idiom one reaches for, `app.add_middleware()`,
assembles the stack in reverse order.

The authentication middleware arrives already built: `holahost-auth` depends on `holahost-http` and
not the other way round, so the factory does not construct it — it only puts it in the right place.
Its `public_paths` is the single declaration of what needs no token: the factory reads it from there
too, in order to exempt the same paths from the `X-Request-ID` requirement. Two lists would drift
apart silently in both directions — a health route answering `422`, or an open route nobody meant to
open.

The same factory closes two more things that nothing else would catch: every router is mounted under
the service's base path (a router that forgets the prefix is unreachable through the gateway, and for
a health route that means the rollout's smoke check never gets to it), and the exception handlers are
always registered (an application with the edge in place and no error mapping registered answers
`500` to everything the service publishes).

## What is deliberately not extracted

Written down so that the question does not come back:

- **Base classes for value objects and entities, and IDs over `uuid.UUID`.** The saving is a dozen
  lines; the price is a shared domain layer across services that are obliged to change for different
  reasons.
- **A repository base class.** Binding the owner is three lines on top of `bind_rls_owner`; a base
  class would fix the repository's **set of methods**, and that is different for every service.
- **`API_BASE_URL`.** Two lines and the rule "a module with no imports, because the container's
  `HEALTHCHECK` reads it" — importing from a library would break that rule.
- **The health router.** Eight lines, and what a readiness check consists of differs per service. The
  only thing shared here is the response contract (`{"status": …}`, `200`/`503`, under the base
  path), and that is written above.
- **The SQL of RLS policies.** A migration is history: it records what was applied, and a helper
  changed later would change the meaning of migrations already applied. The recipe is in
  `holahost-db`'s README.
- **Route-level metrics.** A filter that needs to know a route or a domain field lives in the
  service's Terraform root, next to the code that writes that field.

## Why these are libraries rather than a copy per service

Not for the line count. Every extracted piece is one of those that break silently.

**The middleware.** The framework parses the request body while assembling the handler's arguments —
that is, **before** it starts resolving its dependencies. A check written as a `Depends` fires only
after the upload has been accepted in full. Measured on `rag-documents`: a 50 MiB `POST` with no
`Authorization` header was received down to the last byte and only then answered `401`. Nothing
inside the routes can fix that.

**The error handler.** Nothing inventive, but each part has to be got right: an unpublished subclass
must answer with its ancestor's identity, or a code that is in no schema ends up on the wire; the
dictionary must be closed, or an unaccounted-for exception carries its own message outside;
`X-Request-ID` has to be echoed back by hand from the one handler Starlette binds outside the user
middleware; and the chosen type has to be taken out of that handler, because it re-raises after
writing the response and uvicorn then prints a traceback outside the JSON log.

**Storage.** `QueryCanceled` is a concurrency failure, because a lock-wait timeout is one and the
transaction is already rolled back. `InsufficientPrivilege` is an integrity violation, because that
is what an RLS `WITH CHECK` rejection looks like. A bare `SQLAlchemyError` with no `.orig` is
unavailability, because that is how a pool checkout timeout and a connection invalidation arrive. A
mistake in any of the three turns a retryable failure into a 500, or makes a defect be retried. Plus
two ways to corrupt a password: a DSN assembled by interpolation breaks on `@`, and a role password
assembled through `literal_processor` doubles a `%` — and both are discovered only when a generated
password first contains the character in question.

**The logger.** An allowlist check written as an `assert` is stripped by `-O`, which makes the
protection against content leaking into the log a no-op in exactly the deployment where the flag is
turned on.

Repository-level artefacts are shared by every service and already exist at the repository root:
`.tool-versions` (the toolchain versions), `.pre-commit-config.yaml` (one set of hooks, mirrored in
CI), `CONTRIBUTING.md` (naming conventions, Conventional Commits, GitFlow, branch rules) and
`.github/PULL_REQUEST_TEMPLATE.md`. Service specifications do not override them; a service diverging
from these files has to justify it in its own specification.

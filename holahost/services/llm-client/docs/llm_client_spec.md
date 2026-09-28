# llm-client — technical specification of the microservice

> A **Resource Service** of the Holahost platform (see `holahost/docs/holahost_frame.md`). A facade
> over external large-language-model providers; it owns the **Provider + Model + Budget + Usage**
> domain (the registry of providers and models comes from git config, not from the database).
>
> **Path convention:** `backend/…`, `infra/…`, `docs/…` are relative to the service's root
> (`holahost/services/llm-client/`); "the repository root" means the root of the monorepo.
>
> **Self-containedness:** this document reads without the specifications of other services.
> Everything shared platform-wide is in the framework specification, and that is what is referenced.
>
> **Dynamic sections** at the end of the document: "Deferred decisions", "Extensions", "Draft ADRs".

---

## Stage 1. Problem Statement + Opportunity Brief + User journey map

### 1.1 Problem Statement

The reason to build this: Holahost's services need access to external LLM providers. Without a shared
facade, every service duplicates the provider's SDK, its key, the retry policy for `429` and
overload, and usage accounting; the platform's spend is visible at no single point, and changing the
model requires edits in N services.

### 1.2 Opportunity Brief

We are building a Resource Service — the platform's single point through which calls to LLMs go. The
domain: `Provider` (the registry of providers), `Model` (a provider's model: `max_context`,
`max_output`, price per 1M tokens), `Budget` (a spend ceiling over a window plus the policy on
exhaustion), `Usage` (the fact of spend for one call). The only substantive operation is
**generate**: `system` + `messages` + parameters → text + usage. What the service gives everyone
else:

| Capability | What it takes off the caller |
|---|---|
| A single `generate` operation | knowing the provider's SDK and HTTP contract |
| Logical model aliases (`fast` / `quality` / `default`) resolved in config | hardcoded vendor model names; changing the platform's model becomes an edit to one service's config |
| Centralised retries with backoff on upstream `429` / overload / 5xx | a retry policy of its own in every service |
| Failover to the next provider in the chain once retries are exhausted | every LLM consumer failing when one provider goes down |
| Budgets with an active policy: `reject`, or `downgrade` to a cheaper model | uncontrolled spend, and a hard refusal where a cheaper answer would do |
| A usage log broken down by caller, provider and model | no visibility of the platform's spend |
| Provider keys held by this service alone | the secret spreading across services, and rotation in N places |

The service has no product domain: the prompt always arrives from outside, and the scenarios
("answer the guest" and others) live with the caller. How it joins the product: the service is part
of the platform's first vertical slice, on which the framework specification's topology is checked —
the `backbone` network, offline JWT validation, layered rate limiting, independent deployment.

**The iteration's success criterion** (an infrastructure service has no product metrics — recorded
deliberately): generation works end to end against the local dev stack when called by the
`guest-reply` CLI, and updating the service does not touch its neighbours. The technical metrics are
**Stage 8**.

### 1.3 User journey map

There are no direct human users. The actor is a calling client with an s2s token; in this iteration
the only client is the `guest-reply` CLI. The map has two parts: the lifecycle of a **generation
request** (§1.3.1) and the lifecycle of the service's **long-lived resources** — `Provider`, `Model`,
`Budget`, `Usage` (§1.3.3).

#### 1.3.1 State machine of a generation request

```mermaid
stateDiagram-v2
    [*] --> accepted: generate (system + messages + model|alias)
    accepted --> resolved: alias/id -> a concrete provider model
    accepted --> rejected_model: the model/alias is unknown, or the provider is disabled
    resolved --> rejected_context: the estimated input exceeds the model's max_context
    resolved --> budget_ok: neither the caller's nor the provider's budget is exhausted
    resolved --> exhausted: the budget is exhausted
    exhausted --> rejected_budget: every candidate's provider budget, or the caller's under the reject policy
    exhausted --> downgraded: the caller's budget under the downgrade policy
    downgraded --> budget_ok: the cheaper model, charged to the caller's downgrade pool
    downgraded --> rejected_budget: no cheaper model, or its pool or provider budget is exhausted
    budget_ok --> calling: calling the provider
    calling --> completed: 200
    calling --> refused: the model declines this content
    calling --> retrying: 429 / 5xx / timeout
    calling --> failing_over: the vendor rejects the request itself
    retrying --> calling: attempts remain
    retrying --> failing_over: attempts exhausted, a candidate remains
    failing_over --> calling: switching to the next candidate
    retrying --> failed_upstream: attempts and candidates are exhausted
    completed --> accounted: writing Usage + incrementing the Budget counters
    refused --> accounted: the refusal was paid for, so it is recorded too
    accounted --> [*]
    rejected_model --> [*]
    rejected_context --> [*]
    rejected_budget --> [*]
    failed_upstream --> [*]
```

#### 1.3.2 Transitions and events

| State | Event | Next state | What the caller sees |
|---|---|---|---|
| `accepted` | the alias or `model_id` resolves to an available model | `resolved` | — |
| `accepted` | the alias or `model_id` is unknown, or the provider is disabled | `rejected_model` | 400 `UnknownModelError` |
| `resolved` | the input is longer than the model's `max_context` | `rejected_context` | 422 `ContextOverflowError` |
| `resolved` | the provider budget of every candidate is exhausted, or the caller's own under policy `reject` | `rejected_budget` | 429 `BudgetExhaustedError` plus the reset time |
| `resolved` | the caller's own budget is exhausted, policy `downgrade`, a target can serve the request and neither the caller's downgrade pool nor that target's provider budget is exhausted | `budget_ok` | — (the actual model comes back in the response) |
| `downgraded` | no target can serve the request, or the caller's downgrade pool is exhausted too | `rejected_budget` | 429 `BudgetExhaustedError` plus the reset time |
| `calling` | the provider answered `200` | `completed` → `accounted` | 200 + text + usage + the actual provider and model |
| `calling` | the model declined the content (`200` with confirmed usage) | `refused` → `accounted` | 422 `ContentRefusedError`; the spend is recorded |
| `calling` | the provider answered `429`/5xx or timed out, attempts remain | `retrying` → `calling` | — (invisible from outside) |
| `calling` | the vendor rejected the request itself (a revoked key, a model it does not know) | `failing_over` → `calling` | — (invisible from outside); no candidate left and no transient failure → 500 |
| `retrying` | attempts exhausted, a candidate remains | `failing_over` → `calling` | — (invisible from outside) |
| `retrying` | attempts and candidates are exhausted | `failed_upstream` | 502 `UpstreamLlmError` (retryable) |
| any | no JWT, an invalid one, or the wrong `aud` | unchanged | 401 |
| any | the per-service rate limit was exceeded | unchanged | 429 + `Retry-After` |

The numbers — the attempt limit, backoff, timeouts, the budget's window and size, the composition of
the fallback chain — are Stage 3. The error body's format and the full list are Stage 7.

The response always carries the **actual** provider and model: both a budget `downgrade` and a
`failover` on provider failure have to be visible to the caller, or it cannot tell a downgraded
answer from the one it asked for.

#### 1.3.3 Long-lived resources

| Resource | States | What changes them |
|---|---|---|
| `Provider` | `enabled` ⇄ `disabled` → `removed` | an edit to the service's config (git) plus a rollout |
| `Model` | `available` ⇄ `deprecated` → `removed`; belongs to a provider | the same; an alias is pointed at another model without the callers being involved |
| `Budget` | the current window's state: `open` → `exhausted`; a new window is a new budget with a new identity | it grows with every successful call; the repository assembles it as an aggregate over the usage log |
| `Usage` | an append-only, immutable record | a provider call with confirmed figures — an answer, or a content refusal |

`Usage` is written only from figures the provider confirmed — an answer, or a content refusal, which
the vendor bills the same → a record in the usage log and an increment of the counters. A call that
produced no confirmed figures accrues no spend; on `failover` the spend is charged to the provider
that actually answered. The budget check happens before the provider
call, against the current window's counter; a partially consumed window does not block a call that
may exceed it — overspend within a single call is accepted.

#### 1.3.4 Entry points

| Caller | Token | Operations | In this iteration |
|---|---|---|---|
| the `guest-reply` CLI | s2s, `client_credentials` | `generate` | yes |
| an Orchestration Service (e.g. a chat assistant) | s2s or exchanged | `generate` | no (an extension point) |
| any Holahost service | s2s | reading its own spend and remaining budget | no (an extension point) |

---

## Stage 2. User Stories + Acceptance Criteria

The roles:
- **Caller** — a platform service or tool with an s2s token that calls generation; in this iteration
  that is `guest-reply-cli`.
- **Operator** — whoever deploys the service, keeps the registry of providers and the budgets, and is
  answerable for the platform's spend.

The acceptance criteria reference parameters by symbolic name; the values are fixed in Stage 3.

### 2.0 Parameter table

| Parameter | Purpose |
|---|---|
| `MODEL_ALIASES` | the "logical alias → provider + model" table |
| `MODEL_TOKENS_PER_SECOND` | a conservative generation speed for the model — an input to the pre-flight check |
| `IDEMPOTENCY_KEY_TTL` | the window in which a repeat request with the same key is recognised |
| `FALLBACK_CHAIN` | the ordered candidates an alias resolves to — the order tried during failover |
| `PROVIDER_TIMEOUT` | the timeout of one call to a provider |
| `RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_BASE`, `RETRY_TOTAL_BUDGET` | the upstream retry policy |
| `MAX_INPUT_BYTES` | the maximum request body, measured whole — `system`, `messages` and the JSON around them |
| `MAX_OUTPUT_TOKENS` | the ceiling on the answer's length |
| `BUDGET_WINDOW`, `BUDGET_CAP_PER_CLIENT`, `BUDGET_CAP_DOWNGRADE_PER_CLIENT`, `BUDGET_CAP_PER_PROVIDER` | the budget's window and ceilings |
| `ON_BUDGET_EXHAUSTED`, `DOWNGRADE_TARGETS` | the caller's policy on exhaustion of its own budget and the cheaper models it falls back to |
| `GENERATION_P95_BUDGET` | the target p95 of generation time |
| `RATE_LIMIT_GENERATE` | the generation limit: per calling integration for a service token, per user for an exchanged one |
| `JWT_CLOCK_SKEW` | the clock-skew allowance when checking `exp`/`iat` |
| an error's `code` | the error class's name; the list and the body are Stage 7 |

### US-L01: Generation from an external prompt

> As a Caller, I want to send my own system prompt and messages and get generated text back, so that I do not depend on any provider SDK.

**AC:**
- The request takes `system`, a list of `messages`, a model identifier (an alias or a `model_id`) and
  generation parameters; on success, `200` with the text.
- The service neither replaces nor augments the `system` it was sent: the provider receives exactly
  what the caller sent.
- The response contains: the text, `usage` (input and output tokens), the **actual** provider and
  model, and the reason generation stopped.
- A request larger than `MAX_INPUT_BYTES` → `413 PayloadTooLargeError`, before the body is read
  (§8.1).
- An empty `messages` list → `422 InvalidPayloadError` (platform validation, §7.4).
- A requested `max_tokens` above `MAX_OUTPUT_TOKENS` is truncated to the ceiling, which the request
  schema publishes — that is where a caller reads the limit, and the response carries no field about
  the truncation. A value below 1 is refused with `422 InvalidPayloadError`.
- The response time with no retries is within `GENERATION_P95_BUDGET` (p95).
- No product prompt is stored in the service's codebase (checked by the absence of prompt templates
  in the repository).
- Roles are passed to the provider in the composition and order in which they arrived: `system` is
  not glued to `messages`, the order of messages is not changed, and the service adds no instructions
  of its own.
- The request accepts an idempotency key. A repeat with the same key within `IDEMPOTENCY_KEY_TTL`,
  while the first is in flight or already finished, → `409 DuplicateRequestError`; no second provider
  call is made and no second usage record appears.
- The answer to a duplicate does not carry the first generation's text: only the state and `usage`
  are kept against the key, and in process memory at that — the protection holds for the life of that
  process and on one instance.

### US-L02: Choosing a model through a logical alias

> As a Caller, I want to ask for `fast` or `quality` instead of a vendor model name, so that the platform can change models without touching my code.

**AC:**
- An alias from `MODEL_ALIASES` resolves to an ordered list of "provider + model" candidates; the
  first of them is called, and which one answered is visible in the response.
- An unknown alias or `model_id` → `400 UnknownModelError`, with the list of available aliases in
  `details`.
- An alias left with no candidate of an enabled provider, or a removed model → `400
  UnknownModelError`: to the caller "the alias is gone" and "every model behind it is switched off"
  are the same fact, and the available aliases are the remedy for both.
- Changing an alias's target in the config changes the actual model with no change on the caller's
  side.

### US-L03: Transparent upstream retries

> As a Caller, I want transient provider failures retried inside the service, so that I do not implement backoff in every service.

**AC:**
- A provider answering `429` or `5xx`, or a `PROVIDER_TIMEOUT` timeout, causes a repeat with
  exponential backoff from `RETRY_BACKOFF_BASE`.
- The number of attempts is bounded by `RETRY_MAX_ATTEMPTS` per candidate model and the total time by
  `RETRY_TOTAL_BUDGET`; exhausting either stops the repeats.
- An attempt is not started unless a full answer still fits the time left, and a pause that would
  leave no room for the attempt after it is not waited out: the next candidate needs no wait. Both
  spare the caller a generation paid for and then cut off by the service's own timeout.
- Success after retries is returned to the caller as an ordinary `200` — how many attempts there were
  is invisible from outside, but is written to the log and to a metric.
- Errors that are not transient (`400`, `401`, a content refusal) are not repeated.
- If the provider sent a `Retry-After`, the pause is taken from it rather than from the backoff
  formula.

### US-L04: Failover between providers

> As a Caller, I want the service to switch to another provider when the primary is down, so that a single vendor outage does not stop the platform.

**AC:**
- Having exhausted the retries at the current candidate, the service moves to the next candidate of
  the alias and repeats the request there. A candidate that cannot serve the request — its context,
  the time left, or its provider's budget — is passed over rather than refused: what failed is a
  provider, not the request.
- A request naming a `model_id` has one candidate and is never answered by another vendor's model:
  the caller pinned the model.
- The switch happens for a transient failure and for a request the vendor itself rejected — a revoked
  key, a model it does not know — because both are specific to that vendor. A content refusal is not
  carried over: the cause is the content, and another vendor is not shopped for a different verdict.
- Exhausting the candidates → `502 UpstreamLlmError`, marked as retryable. If no candidate failed
  transiently and every one rejected the request, the cause is this service's configuration and the
  answer is `500`.
- The response returns the provider that actually answered, and the spend is charged to that one.
- Disabling a provider in the config excludes it from the chain without restarting the callers.

### US-L05: Refusal when the budget is exhausted

> As an Operator, I want calls to stop when a budget cap is reached, so that a runaway caller cannot drain the platform's account.

**AC:**
- The budget check happens **before** the provider is called.
- The `BUDGET_CAP_PER_CLIENT` ceiling exhausted under the `reject` policy, or the
  `BUDGET_CAP_PER_PROVIDER` ceiling exhausted for the provider of every candidate → `429
  BudgetExhaustedError`, with which ceiling was exhausted and the start time of the next window in
  `details`. A candidate whose provider alone is out of budget is passed over, as in failover
  (US-L04).
- A budget refusal creates no usage record.
- One caller exhausting its budget does not affect the others — the ceilings are independent.
- The start of a new `BUDGET_WINDOW` restores access with no manual action.

### US-L06: A cheaper answer instead of a refusal

> As a Caller, I want an optional cheaper answer instead of a hard refusal when the budget is out, so that non-critical flows keep working.

**AC:**
- Under the `downgrade` policy, exhaustion of the caller's own budget (`BUDGET_CAP_PER_CLIENT`) moves
  the request to `DOWNGRADE_TARGETS` rather than refusing it: the targets are tried in order, and one
  that cannot serve the request — its context, the time left, or its provider's budget — is passed
  over, as a failover candidate is.
- A target the request could already be answered by — one of its own candidates — is passed over
  too: serving it from the downgrade pool would only hand the caller a second budget for the same
  model.
- A downgraded request is charged to a pool of its own, `BUDGET_CAP_DOWNGRADE_PER_CLIENT`, not to the
  exhausted one (B-4).
- Exhaustion of the providers' budgets for every candidate is refused whatever the policy.
- The cheaper model is set by a setting separate from `MODEL_ALIASES`; changing the alias table does
  not affect it.
- The response carries the actual model, so the caller can tell degradation from normality without
  guessing.
- An exhausted downgrade pool → `429 BudgetExhaustedError` naming that pool. If no target can serve
  the request at all — none configured, or none left after the checks above — the answer is `429
  BudgetExhaustedError` on the caller's **own** budget: that is what ran out, and the cheaper model's
  limits are neither what the caller asked for nor anything it can fix.
- The policy is the caller's, not a budget's: it has a default and is overridden per `client_id`.

### US-L07: The bounds of input and output

> As a Caller, I want oversized requests rejected predictably, so that I learn about limits from the contract and not from a vendor error.

**AC:**
- An input estimate plus `max_tokens` greater than the chosen model's `max_context` → `422
  ContextOverflowError`, with the model's limit and that sum in `details`. The answer's ceiling is
  counted in because a vendor whose window covers both refuses the pair, not the input alone.
- The check happens before the provider is called: a vendor context-overflow error is never passed
  through. The estimate is an **upper bound** — the input's UTF-8 bytes, since a token never spans
  less than a byte — so nothing overflows at the vendor that passed here, at the price of refusing a
  dense-script input that would in fact have fitted.
- On a `downgrade`, the context is re-checked against the **new** model's `max_context`.
- The response does not exceed `MAX_OUTPUT_TOKENS`.
- If the estimated generation time (`max_tokens` / `MODEL_TOKENS_PER_SECOND`) does not fit **one
  attempt** — the smaller of `PROVIDER_TIMEOUT` and what is left of `RETRY_TOTAL_BUDGET` — the request
  is refused **before** the provider is called, with an error code of its own; `details` carries the
  largest `max_tokens` that would have fitted, a figure one call can actually deliver.
- A pre-flight refusal takes milliseconds and creates neither a provider call nor a usage record.

### US-L08: Usage accounting

> As an Operator, I want every successful call recorded, so that I can see where the platform's LLM spend goes.

**AC:**
- Every call the provider confirmed usage for — a successful answer, and a content refusal, which is
  billed just the same — creates a record with: `client_id`, `sub`, the provider, the model, the input
  and output tokens, the duration, and the `X-Request-ID`.
- The figures come from the provider's response, not from an estimate of the service's own.
- A call that produced no confirmed usage creates no usage record and does not move the budget
  counters.
- The records are immutable: the contract provides for neither updates nor deletion.
- The texts of `system`, `messages` and the answer are not stored in a usage record.
- An exhausted ceiling survives a container restart: the budget's state is derived from the usage log,
  so a restart does not hand back a spent limit (unlike the rate limit, US-L10).
- A call that ended in a provider timeout creates no usage record — even though the provider has
  probably spent the tokens. This gap in accounting is recorded in ADR B-12 and is not closed by the
  service estimating the spend itself.

### US-L09: Authentication and authorization

> As an Operator, I want every route except health to require a valid token, so that provider keys are reachable only through authorised calls.

**AC:**
- The shared `holahost-auth` library (framework specification, "Reusable shared entities") is mounted
  on every route except `GET /api/llm-client/health`. Its `AuthConfig` reads its five variables from
  the environment itself — the names are the platform's, and the only value belonging to the service
  is `EXPECTED_AUDIENCE`.
- A missing `Bearer` token, a JWT that does not parse, an unexpected `alg`, an invalid signature, an
  expired `exp` (with the `JWT_CLOCK_SKEW` allowance), a foreign `iss`, or an `aud` without
  `llm-client` → `401`, with no reason disclosed in the body.
- An unknown `kid` → one JWKS re-fetch, then `401`.
- `403` only for a valid token without the rights.
- Provider keys never leave the service: they are returned in no response, written to no log, and
  accepted in no incoming request (there is no BYOK header in the contract).

### US-L10: Rate limiting

> As an Operator, I want per-caller request limits, so that one client cannot monopolise the service.

**AC:**
- The limit is applied after `holahost-auth` and before the handler; the key is `(bucket,
  is_service)` over `client_id`/`sub`. The mechanism is `holahost_http.RateLimitMiddleware` with
  `InMemoryRateLimiter`; the service declares the buckets and the ceilings.
- `POST /api/llm-client/generate` falls into the bucket `generate` with the `RATE_LIMIT_GENERATE`
  ceilings; health is not limited.
- Exceeding it → `429` with `Retry-After`.
- The counters live in process memory and are not persisted — a restart zeroes the window. That is
  acceptable: the limit protects the service from overload. The budget (US-L05), by contrast, is
  persisted, because it is about money and has a long window.
- The rate limit and the budget are independent mechanisms: one firing does not cancel the other's
  check, and the error codes differ.

### US-L11: The error contract

> As a Caller, I want one machine-readable error shape across providers, so that I never parse vendor errors.

**AC:**
- The error body is `{ error: { code, message, details } }` from `holahost-http`; `code` is the
  **error class's name**, not a separate string taxonomy.
- The provider's vendor codes and messages are not passed through; they are written to the log.
- Every error has retry semantics attached; `UpstreamLlmError` is retryable, `ContextOverflowError`,
  `UnknownModelError` and `ContentRefusedError` are not — the last because the same content is
  declined again.
- `message` goes on the wire but is not in the published schema: it is for a human reading a log,
  while a caller branches on `code` and reads `details`.
- The message contains no fragments of the prompt, of the answer, or of provider keys.

### US-L12: Health and smoke

> As an Operator, I want a health endpoint, so that deploys can be verified automatically.

**AC:**
- `GET /api/llm-client/health` is reachable without authorization and answers `200` when the service
  is ready to take requests. The path is under the base path: the gateway routes `/api/<svc>/*`
  without rewriting, so a bare `/health` is reachable only from inside the compose network and the
  rollout's smoke check would never get to it.
- Readiness includes the accounting database being reachable; health makes no provider calls — it
  must neither spend money nor depend on a vendor.
- The container listens on port 8080 and is attached to the `backbone` network; the port is not
  published outside.

### US-L13: Logs without prompts or secrets

> As an Operator, I want logs that never contain prompt text or keys, so that observability does not leak content.

**AC:**
- What never reaches the logs: `system`, `messages`, the answer's text, provider keys, a token's body.
- What does reach the logs: `X-Request-ID`, `client_id`, `sub`, the provider, the model, the token
  counts, the number of attempts, whether a `downgrade` or `failover` happened, error codes, and
  durations.
- The incoming request's `X-Request-ID` is logged and propagated into the outgoing provider calls
  where the protocol allows it.
- The logs are structured (JSON) and the set of fields is governed by an allowlist; the mechanism is
  `holahost-observability`, and the service declares only its own fields beyond the platform core.
- The completion event is `op_completed`, one per request, with the platform's core fields (framework
  specification, "The operation-completion event contract").

### US-L14: Managing the provider registry

> As an Operator, I want to add, disable or re-point providers and models in config, so that vendor changes never require changes in calling services.

**AC:**
- Providers, models and the alias table are set by the service's config; callers are not notified of
  edits and change no code.
- Disabling a provider drops its models from every alias's candidates, and so from failover too.
- A provider's key is read from Secrets Manager through a reference in the config; the secret's value
  never reaches git.
- An incorrect config — an alias pointing at a non-existent model, a provider with no key — is caught
  at startup: the service does not come up and writes the reason.

### 2.15 Coverage of the user journey map (§1.3)

| Transition on the map | Covered by |
|---|---|
| `accepted → resolved` | US-L02 |
| `accepted → rejected_model` | US-L02 |
| `resolved → rejected_context` | US-L07 |
| `resolved → budget_ok` | US-L05 |
| `resolved → exhausted → rejected_budget` | US-L05 |
| `exhausted → downgraded → budget_ok` | US-L06 |
| `calling → completed` | US-L01 |
| `calling → refused → accounted` | US-L08 (the spend is recorded), US-L11 (the published error) |
| `calling → retrying → calling` | US-L03 |
| `retrying → failing_over → calling` | US-L04 |
| `retrying → failed_upstream` | US-L03, US-L04 |
| `completed → accounted` | US-L08 |
| The `Provider` / `Model` lifecycle (§1.3.3) | US-L14 |
| 401 / 403 on any operation | US-L09 |
| 429 rate limit on any operation | US-L10 |
| Every refusal branch | US-L11 |

---

## Stage 3. Tech Constraints Doc

### 3.1 System architecture

A self-contained deploy unit: the application container plus a Postgres container (the usage log) in
its own compose project, on the `backbone` network. The only service on the platform with outgoing
traffic to the internet.

```mermaid
flowchart LR
    subgraph SP [staging / prod]
        CALLER[a platform caller] -->|HTTPS| GW[API Gateway]
        GW -->|x-origin-secret| NX[nginx of the platform compose project]
        NX -->|/llm-client/*| API1[llm-client:8080]
    end
    subgraph DEV [dev]
        CLI[guest-reply] -->|HTTP to localhost:port| API2[llm-client]
    end
    API1 --> PG1[(Postgres: the usage log)]
    API2 --> PG2[(Postgres: the usage log)]
    API1 -->|HTTPS| PROV[external LLM providers]
    API2 -->|HTTPS| PROV
```

| Environment | Entry | Who calls |
|---|---|---|
| staging / prod | API Gateway → the platform compose project's nginx → service:8080 (the port is not published) | the platform's services |
| dev | straight to the container's published port, with no gateway and no nginx | a developer's CLI tools |

The service behaves identically in both paths and compensates for the absent perimeter in no way:
there is no branching on environment and no generation of missing headers. `X-Request-ID` is set by
the caller — nginx on staging and prod, a CLI tool on dev.

### 3.2 Code architecture

Clean architecture, with the layers and the `import-linter` contract shared platform-wide (framework
specification, "Reusable shared entities").

```
backend/
  app/
    config/                 # typed settings and reading the provider registry's git config
                            # (the source for the provider repository, read once at startup)
    domain/
      entities/             # identifiable objects with a lifecycle
      value_objects/        # frozen dataclasses with invariants, and ID classes
      exceptions.py
    application/
      dto/                  # use-case commands and results, primitives only
      ports/                # Protocols for external dependencies: the generation provider, the
                            # accounting and budget repositories, the rate limit, the unit of work
      use_cases/            # orchestration on top of the ports
      exceptions/
    infrastructure/
      providers/            # provider adapters over langchain models
      db/                   # SQLAlchemy Core, repositories, migrations; the engine and UoW come from holahost-db
    interface/
      http/                 # FastAPI: the router, the schemas, the error contract, the edge's values
    scripts/                # the composition root
```

Retries, model selection, failover and the budget check are orchestration, so they live in the use
case rather than in the provider adapter. The adapter knows only "call this model with these
messages", and translates what the vendor answers into the port's terms: vendor errors into the
port's three — `TransientProviderError`, `ProviderRejectedRequestError`, `ProviderRefusedContentError`
(§8.0) — and the vendor's stop reason into `FinishReason`, through a mapping table of its own for each
provider.

The adapter is one `GenerationProvider` over langchain chat models, plus a *dialect* per vendor: what
differs between vendors — building the chat model, reading its stop reasons and its errors — is the
dialect's. One chat model per registry model is built at startup, with the SDK's own retries off: the
use case repeats, and an SDK repeating behind its back would spend the deadline twice. `max_tokens`,
`temperature`, `stop` and the attempt's timeout are set per call; the timeout is the wait for the
answer, and setting up the call is bounded apart (§3.7). An empty `system` sends no system block. An answer without the vendor's usage figures is a `ProviderRejectedRequestError` — a defect of
the integration, never recorded as a zero spend.

For `anthropic`:

| `stop_reason` | Result |
|---|---|
| `end_turn`, `stop_sequence` | `FinishReason.stop` |
| `max_tokens`, `model_context_window_exceeded` | `FinishReason.max_tokens` — cut off by a limit either way; after pre-flight the second means a wrong `max_context` in the registry |
| `refusal` (arrives with `200`) | `ProviderRefusedContentError`, carrying the `usage` the response confirmed |
| `tool_use`, `pause_turn`, or a value outside this table | `FinishReason.stop`, and a `vendor_stop_reason_unmapped` warning carrying `vendor_stop_reason`: the answer is paid for, and refusing it would lose the text and the accounting both |

Its errors are read by the SDK's types:

| Vendor error | Result |
|---|---|
| a status of `408`, `409`, `429` or any `5xx` (`529` overload included) | `TransientProviderError` with the status, and the `Retry-After` in seconds when sent (its HTTP-date form is left to the backoff formula) |
| any other status | `ProviderRejectedRequestError` with the status |
| a timeout or a failed connection | `TransientProviderError` without a status — both count as a timeout (§8.4) |
| anything else raised by the call | `ProviderRejectedRequestError` without a status: a response the integration could not read, or a call built wrong |

There are no `infrastructure/auth/` or `interface/http/middleware/` directories: `holahost-auth`
hands over a ready-made middleware and `current_token`, so there is nothing to adapt, and the edge's
middleware and their order are assembled by `holahost_http.create_edge_app`. The service declares the
values — the limit's buckets, the body ceiling, the error for a missing `X-Request-ID`, its own error
contract — but not the sequence (§8.1).

### 3.3 Domain modelling

Lightweight DDD: `domain/entities/` with the `create()` and `from_repo()` factory methods,
`domain/value_objects/` as frozen dataclasses with invariants in `__post_init__`, and ID classes over
`uuid.UUID`. Domain services, aggregates and factories are not used; repositories are Protocols in
`application/ports/`, not in `domain/`. There are no `Clock` or `IdGenerator` ports:
`datetime.now(tz=UTC)` inline, and identifiers are self-generating. The registry of providers and
models is configuration, not persistent state (§3.6).

### 3.4 Technology stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| HTTP | FastAPI + uvicorn, with **synchronous** `def` endpoints (ADR B-7) |
| Provider client | the `langchain` stack: the providers' chat models (`langchain_anthropic` and the like) behind a port |
| Database | Postgres 16, a container in the service's compose project |
| Database access | SQLAlchemy Core 2.0 over `psycopg[binary,pool]`; no ORM |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Authorization | the shared `holahost-auth` library |
| Tests | pytest, with fakes for the ports; no test ever reaches a real provider |
| Logs | structured JSON on stdout, with a field allowlist |

### 3.5 Data storage and lifecycle

| Data | Where | Lifecycle |
|---|---|---|
| Usage records (the log) | Postgres, append-only | indefinitely; pruning is an extension |
| The budget's state | nowhere: an aggregate over the usage log for the current window | computed on every check (§6.1) |
| Idempotency keys | process memory | until `IDEMPOTENCY_KEY_TTL` expires, or until a restart; the volume is bounded by one TTL's traffic, and a live key is never evicted — that would quietly lift the protection against paying twice |
| The registry of providers, models and aliases | the service's git config | changed by a rollout (§3.6) |
| Provider keys | Secrets Manager (staging/prod), `.env.dev` (dev) | rotation is replacing the value plus a restart |
| The texts of prompts and answers | **nowhere** | they live only in the request's memory |
| Rate-limit counters, the JWKS cache | process memory | until a restart |

There is one rule: what is promised to the outside lives in the database, and what protects the
service lives in memory. Spend is a promise — money, reporting — so the log is persistent and the
budget survives a restart through it automatically. The rate limit and the idempotency keys protect
against overload and double payment within the life of a process, so resetting them on a restart is
harmless (ADR B-9).

### 3.6 The registry of providers, models and aliases

Configuration in the service's git repository; only names and references to secrets go into the file,
while the key values live in SM. A change is applied by **rolling out the container**; hot reload is
not introduced — the config takes part in startup validation, and "half the processes on the old
config" is worse than a short restart.

```yaml
providers:
  anthropic:
    enabled: true
    api_key_ref: anthropic-api-key   # the secret's name: holahost/<env>/llm-client/<ref> in SM
    models:                          # `deprecated: true` optionally marks a model (§4.2)
      claude-sonnet-4-6:  { max_context: 200000, max_output: 8192, price_in: …, price_out: …,
                            tokens_per_second: … }
      claude-haiku-4-5:   { max_context: 200000, max_output: 8192, price_in: …, price_out: …,
                            tokens_per_second: … }

aliases:                             # an alias is an ordered list: the first candidate is called,
  default: [{ provider: anthropic, model: claude-sonnet-4-6 }]      # the rest are tried on failover
  quality: [{ provider: anthropic, model: claude-sonnet-4-6 }]
  fast:    [{ provider: anthropic, model: claude-haiku-4-5 }]

downgrade_targets: [{ provider: anthropic, model: claude-haiku-4-5 }]   # the downgrade policy's
                                                                        # targets, in order

on_budget_exhausted:                 # the caller's policy: a default, overridden per client_id
  default: reject
  overrides: {}
```

Failover is a list of models rather than of providers: a provider is not called, a model is, and
which of another vendor's models stands in for this one cannot be derived from the two registries. An
alias names the equivalence explicitly; a request naming a `model_id` resolves to that model alone and
is never answered by another vendor's (US-L04).

An incorrect config means the service does not start and writes the reason (US-L14). The same
procedure checks it at startup and in CI (Stage 12). The file's own rules are reported at once; an
entity's broken invariant stops the check at the first one found, and the models too slow for one
attempt are reported together once every entity is valid:
- a key the file's schema does not know — a misspelt one is an error, not a setting left at its
  default;
- an alias with no candidates, or pointing at a non-existent or deprecated model; an alias named
  like a model id, since a request names either and one string meaning both would resolve by
  accident;
- a model listed twice in one alias, where the repeat would be a failover to the model that has
  just failed, or twice among the downgrade targets;
- a model id under two providers; a downgrade target that does not exist;
- an `api_key_ref` outside kebab-case, since the environment variable the key is read from is
  derived from it;
- an enabled provider with no secret, no models, or no adapter (§3.2); a model breaking its entity's
  invariants (§4.2);
- a model that cannot deliver its answer ceiling within one attempt — `min(max_output,
  MAX_OUTPUT_TOKENS) / tokens_per_second` above `PROVIDER_TIMEOUT` — since every request sending no
  `max_tokens` would then be refused before any call.

A provider's key is read once, at startup. On staging and prod the bootstrap fetches the secret of
every enabled provider and hands it on through the environment variable named after its reference —
`anthropic-api-key` → `ANTHROPIC_API_KEY`; on dev that variable comes from the `.env` file. A missing
key stops the startup. The keys never pass through the service's typed settings: only the
generation adapter needs them, and every other holder of the settings would see them too.

The exhaustion policy (`ON_BUDGET_EXHAUSTED`) is a caller's setting — a default overridden per
`client_id` — not an attribute of a budget: a provider's budget is shared by callers whose policies
differ (§4.3). It reaches the use case as two values from this config rather than through a port of
its own: a table read once at startup has nothing for a port to abstract.

### 3.7 Parameters and limits (numbers)

The time figures below describe the **synchronous mode** and are derived from the API Gateway's
integration ceiling (30 s) with all the retries and failover taken into account. An important caveat:
the service cannot guarantee staying within that ceiling — the duration of a generation does not
follow from the size of the input, and a model is entitled to take longer on the same prompt. So the
ceiling states not a promise but the **boundary of the synchronous mode's applicability**: anything
that does not fit is served by the asynchronous mode (E-3) rather than by raising timeouts. Until E-3
exists, load that does not fit the budget is not served by the service.

| Parameter | Value | Rationale |
|---|---|---|
| `PROVIDER_TIMEOUT` | 20 s for an attempt's answer, and never longer than the time left; setting up the call — connecting, sending the request, taking a pooled connection — is bounded apart, at 1 s a phase | a generation of `MAX_OUTPUT_TOKENS` fits with room to spare; more would not fit the overall budget. It also bounds what pre-flight accepts (§3.7.1): an answer no single attempt could finish is refused rather than paid for and cut off. The setup comes on top rather than out of the answer's share, which would cut off answers pre-flight accepted; at worst it takes 3 s of the 5 s `RETRY_TOTAL_BUDGET` leaves before the ceiling |
| `RETRY_MAX_ATTEMPTS` | 2 (the first plus one repeat), per candidate model | a third repeat does not fit into 30 s |
| `RETRY_BACKOFF_BASE` | 1 s, exponential, jitter ±20 % | the provider's `Retry-After`, when sent, takes priority; a pause that would not leave room for the attempt after it is not taken at all — the next candidate needs no wait |
| `RETRY_TOTAL_BUDGET` | 25 s for the whole request, failover included; one deadline, taken on entering the use case | leaves 5 s for the network and serialisation before the integration ceiling |
| `FALLBACK_CHAIN` | the candidates an alias resolves to, in order; one model per alias in this iteration | with one candidate failover does not fire — the mechanism exists, the configuration of it does not |
| `MAX_INPUT_BYTES` | 256 KiB | more makes no sense in a synchronous path: a generation over such an input will not fit the budget |
| `MAX_OUTPUT_TOKENS` | 1000 | higher risks not fitting `PROVIDER_TIMEOUT` |
| `temperature` range, `MAX_STOP_SEQUENCES` | 0..1; 4 sequences, none empty | the range and the count every configured vendor accepts: outside them a vendor rejects the request, which would be answered `500` for a caller's mistake (§7.2) |
| `BUDGET_WINDOW` | a day, reset at 00:00 UTC, lazily on the first request of a new window | aggregated over the usage log on the fly, so no separate scheduler is needed |
| `BUDGET_CAP_PER_CLIENT` | 2,000,000 input and 200,000 output tokens per day | counted separately: the prices differ by a multiple, and one counter would lie |
| `BUDGET_CAP_PER_PROVIDER` | 10,000,000 input and 1,000,000 output tokens per day | protection of the platform's wallet on top of the per-client ceilings |
| `BUDGET_CAP_DOWNGRADE_PER_CLIENT` | input and output tokens per day, counted separately; the value is a deferred decision | the pool downgraded requests are charged to (US-L06) |
| `ON_BUDGET_EXHAUSTED` | `reject` by default, overridden per `client_id`; applies to the caller's own budget only | a silent downgrade by default should not come as a surprise |
| `DOWNGRADE_TARGETS` | an ordered list in the config, applied only under the `downgrade` policy | separate from the alias table (ADR B-4); tried in order, and a target that cannot serve the request is passed over |
| `MODEL_TOKENS_PER_SECOND` | a conservative estimate of generation speed, set in the config per model | an input to the pre-flight check (§3.7.1); a model whose answer ceiling does not fit one attempt at this speed keeps the service from starting (§3.6) |
| `IDEMPOTENCY_KEY_TTL` | 15 minutes | the window in which a repeat with the same key is recognised as a duplicate |
| `RATE_LIMIT_GENERATE` | bucket `generate`: 600 req/hour for a service token — one counter for the whole calling integration — and 60 req/hour per user of an exchanged token | generation is paid and holds a thread for the whole wait on the vendor, so it is priced apart from the framework's `ingest` and `read`; one number for both token kinds would starve a busy integration or hand each of its users the whole integration's allowance |
| `GENERATION_P95_BUDGET` | 15 s | the path with no retries |
| `JWT_CLOCK_SKEW` | 30 s | from the framework specification |
| Database query timeout | 5 s | usage accounting must not hold a thread longer than the generation itself |

Where a parameter is declared follows who applies its rule, not where its figure came from:
- the figures derived from the gateway's ceiling — `PROVIDER_TIMEOUT`, `RETRY_*`,
  `MAX_OUTPUT_TOKENS`, `MAX_INPUT_BYTES`, `GENERATION_P95_BUDGET` — are application constants
  (`application/limits.py`). Dev has no gateway, yet its figures are the same: the service does not
  branch on environment (§3.1), or dev would accept load that prod refuses. The `temperature` range
  and `MAX_STOP_SEQUENCES` sit beside them: the use case applies them, and they bound what every
  vendor accepts rather than one vendor's model;
- the vendor's facts — `MODEL_ALIASES`, `FALLBACK_CHAIN`, `DOWNGRADE_TARGETS`,
  `MODEL_TOKENS_PER_SECOND`, a model's limits and prices — are in the registry (§3.6): they change
  when a vendor ships or retires a model;
- money and fairness — `BUDGET_CAP_*`, `RATE_LIMIT_GENERATE`, `IDEMPOTENCY_KEY_TTL` — are the
  service's settings: they say how much one deployment may spend, and staging rightly spends less
  than prod. `ON_BUDGET_EXHAUSTED` belongs here by nature but sits in the registry: it maps
  `client_id` to a policy, which environment variables express badly;
- `BUDGET_WINDOW` is the domain's: a window other than a UTC day changes the aggregate's query, not
  a number.

#### 3.7.1 What makes the synchronous mode predictable

Since staying within the ceiling is not guaranteed, three mechanisms are introduced — they are
cheaper than a full asynchronous mode and remove its most expensive consequences (ADR B-12).

**Pre-flight refusal.** Before the provider is called, the generation time is estimated as
`max_tokens / MODEL_TOKENS_PER_SECOND` and compared against **one attempt's** worth of time — the
smaller of `PROVIDER_TIMEOUT` and what is left of `RETRY_TOTAL_BUDGET`. Against the whole budget it
would accept answers no single call could finish: a model between the two figures would pass the check
and then be cut off by the service's own timeout, with the vendor paid and the spend outside the log
(B-12). Not fitting means the request is refused immediately with an error code of its own, stating
which `max_tokens` would have fitted — a number achievable in one call, not merely within the budget.
The caller gets an answer in milliseconds instead of a timeout at the thirtieth second, and the
provider is spared a request that was doomed from the start.

The estimate carries no term for processing the input. Both figures it would need — the prefill speed
and the input's token count — are guesses today: `MODEL_TOKENS_PER_SECOND` itself awaits a measurement
(Deferred decisions), and the token count is an upper bound by bytes (US-L07), so a pessimistic term
would refuse requests that fit while an optimistic one would do nothing. What a large input with a
small `max_tokens` costs is a timeout rather than a millisecond refusal — the state before pre-flight
existed. The `op_completed` fields `provider_ms` and `input_tokens` are what will calibrate the term.

**The idempotency key.** The caller sends a key; for `IDEMPOTENCY_KEY_TTL` the service remembers that
a request with that key is already in flight or already finished, and answers a repeat with a
conflict rather than with a second paid generation. The key holds only the state and `usage` — **the
answer's text is not stored** — so a repeat does not deliver the result, it only prevents paying
twice. Delivering the result after a dropped connection is part of the asynchronous extension E-3.

**An acknowledged gap in accounting.** If the provider did not answer within `PROVIDER_TIMEOUT` it
has most likely already spent the tokens, while `Usage` is written only from confirmed figures —
which means that spend will not reach the usage log. The gap is accepted deliberately: the
alternative is estimating the spend ourselves and spoiling the accounting's trustworthiness.
Reconciliation against the provider's billing is an extension.

### 3.8 Security

| Aspect | Decision |
|---|---|
| Authentication | JWT offline through `holahost-auth` on every route except `GET /api/llm-client/health` |
| Authorization | by the `client_id` from the token: budgets, limits and policies attach to it |
| Provider keys | in SM only; read at startup, returned in no response, written to no log, and accepted in no incoming request (there is no BYOK header in the contract) |
| Outgoing traffic | only to the provider domains from the config; TLS certificate verification is mandatory and is disabled in no environment |
| The caller's data | `system`, `messages` and the answer are neither stored nor logged; only counters reach the usage log |
| Provider errors | not passed through verbatim: vendor codes and texts stay in the logs |
| Input | the body size is bounded before parsing, and the context estimate is computed before the provider is called |
| CORS | not configured — no browser reaches this service, and direct frontend access to generation is not planned at all (it is an Orchestration Service's operation, not a UI's) |
| Prompt injection | An injection is an attack on the prompt's meaning, so the defence belongs to the prompt's owner — in this iteration the CLI: untrusted data only in the user role, no instructions taken from retrieved content, the output checked. The service takes no part in that, but is obliged **not to destroy** the caller's defence: the roles are passed to the provider in the same composition and order, `system` is not glued to `messages`, and the service adds no instructions of its own and rewrites no content |

### 3.9 Out of scope for this iteration

- Streaming the answer (an extension).
- Tool use / function calling, structured output, multimodal input.
- The provider's prompt caching.
- Embeddings as an operation of this service: the platform's embedding model is local and has no
  external provider, so it lives with the owner of the documents rather than behind this facade.
- Providers' batch APIs and deferred generations.
- More than one candidate per alias, and so a second provider (the mechanism is implemented, the
  configuration is not).
- A caller reading its own spend and remaining budget (an extension).
- Converting spend into money: prices are kept in the config, but no reporting is built on them.

### 3.10 Happy path at component level

```mermaid
sequenceDiagram
    participant CLI as the caller (guest-reply)
    participant API as llm-client
    participant PG as Postgres
    participant PR as the LLM provider

    CLI->>API: generate (system, messages, alias, Bearer)
    API->>API: holahost-auth -> rate limit -> resolve the alias -> estimate the context
    API->>PG: check the budget counters (client and provider)
    PG-->>API: the window's remainders
    API->>PR: the generation request
    PR-->>API: text + usage
    API->>PG: transaction: write the usage record
    PG-->>API: commit
    API-->>CLI: 200 text + usage + the actual provider and model
```

---

## Stage 4. Domain Entities

The values of the parameters the invariants reference are in §3.7.

The criterion for an entity is identity that survives a change of attributes: a provider with
`enabled: false` is still the same provider, and a client's budget for a day is still the same budget
as the amount spent grows. Neither the storage nor the object's lifetime in memory affects this: the
source of the data — a table, git config, an aggregate over the log — is a repository's
implementation, not the object's nature. By that criterion there are five entities: `Provider`,
`Model`, `Budget`, `UsageRecord`, `IdempotencyRecord`.

### 4.1 Value objects

| VO | Based on | Invariants |
|---|---|---|
| `GenerationId` | `uuid.UUID` | generated by its own `new()` for each generation; the usage record's identity. Not `X-Request-ID`: that one is chosen by the caller, and two paid generations may share it |
| `ClientId` | `str` | non-empty; taken from a token claim, not from the request body |
| `Subject` | `str` | non-empty; the token's `sub` (for s2s it equals `client_id`) |
| `ProviderName` | `str` | a value from the registry; an unknown name is not a VO but a resolution error |
| `ModelId` | `str` | the model's identifier at the provider |
| `TokenCount` | `int` | ≥ 0 |
| `Usage` | a pair of `TokenCount` | input and output separately: the prices differ by a multiple, and one counter would lie |
| `IdempotencyKey` | `str` | 1…128 characters; unique within a `ClientId` and an `IDEMPOTENCY_KEY_TTL` window |
| `Message` | role + text | the role is `user` (B-14); the text contains non-whitespace characters and is kept unchanged |
| `FinishReason` | an enumeration: `stop`, `max_tokens` | the same across all providers; a stop sequence is not told apart from a natural end, because not every provider reports it; a content refusal is a provider error, not a value (§3.2) |

### 4.2 `Provider` and `Model`

Entities with the identities `name` and `(provider, id)` respectively. Their state changes between
rollouts — disabling a provider, marking a model deprecated, editing the ceilings — and after any such
edit it is the same provider and the same model: the usage log's records and the aliases refer to
them. The source of the data is git config (§3.6) rather than a table; the repository reads it once at
startup and hands back typed objects, not settings dictionaries.

`Provider`:

| Field | Type | Note |
|---|---|---|
| `name` | `ProviderName` | |
| `enabled` | `bool` | a disabled one is excluded from alias resolution and from the failover chain |
| `api_key_ref` | `str` | a reference to a secret, not the value; may be absent only for a disabled provider |

`Model`:

| Field | Type | Note |
|---|---|---|
| `provider` | `Provider` | a model does not exist without a provider, so this is the object itself rather than a name: no separate "permitted provider + model pair" type is then needed |
| `id` | `ModelId` | |
| `max_context` | `int` | > 0 |
| `max_output` | `int` | > 0; the actual ceiling on an answer is `min(max_output, MAX_OUTPUT_TOKENS)` |
| `price_in`, `price_out` | `Decimal` | the price per 1M tokens; stored for reporting and not used in this iteration's calculations |
| `tokens_per_second` | `int` | > 0, or the pre-flight estimate (§3.7.1) divides by zero |
| `deprecated` | `bool` | a marked model still resolves, but no new aliases are pointed at it |

**Invariants:** an enabled provider has a resolvable reference to a secret; `max_context` is strictly
greater than `max_output`; `tokens_per_second` > 0. A violation is caught at startup — the service
does not come up (US-L14). The key's value is not held in the object: it is read when the provider is
called and never reaches the domain.

`Provider` holds no models: `Model` refers to its provider, and a reference back cannot be built
between immutable objects. "An enabled provider has at least one available model" is a property of
the whole registry, checked when the registry is loaded (§3.6).

**Lifecycle:** the state changes with a rollout of a new configuration; a provider or model removed
from the config stops resolving but stays readable in the usage log as a historical fact.

### 4.3 `Budget`

An entity with the identity `(scope, key, window_start)`: "client X's spend for day D" remains the
same budget as `spent` grows. It has no table of its own — the repository assembles it from an
aggregate over the usage log for the window plus the ceilings from the config (§6.1); that is a way of
implementing it, not a reason to consider it something else.

| Field | Type | Note |
|---|---|---|
| `scope` | an enumeration | `client` (the caller's own spend), `client_downgrade` (the caller's downgraded requests — a pool of its own, US-L06), `provider` |
| `key` | `ClientId \| ProviderName` | `ClientId` for both client scopes, `ProviderName` for `provider` |
| `window_start` | `datetime` (UTC) | midnight UTC of the current day, computed by the repository and bound into the aggregate's query (§6.1); not a stored field |
| `spent` | `Usage` | an aggregate over the usage log: input and output separately |
| `caps` | `Usage` | the window's ceilings from the config |

**Invariants:** `spent` never decreases within a window — a consequence of the log being append-only;
the ceilings are positive; the key's type matches the scope. The exhaustion policy is not a budget's
attribute: it belongs to the caller, while a provider's budget is shared by callers whose policies
differ.

**Lifecycle:** the object lives for the duration of one check. Resetting the window is neither an event
nor an operation: a new day changes the aggregate's range, and there is nothing to zero.

### 4.4 `UsageRecord`

| Field | Type | Note |
|---|---|---|
| `id` | `GenerationId` | generated for the generation (§4.1) |
| `request_id` | `str` | the request's `X-Request-ID`, for correlation with the logs |
| `client_id` | `ClientId` | |
| `subject` | `Subject` | |
| `provider`, `model` | `ProviderName`, `ModelId` | the **actual** ones, not the requested ones |
| `usage` | `Usage` | the provider's figures, not an estimate of our own |
| `latency_ms` | `int` | ≥ 0 |
| `downgraded`, `failed_over` | `bool` | markers of the policies that were applied |
| `created_at` | `datetime` (UTC) | |

**Invariants:** the record is immutable; it is created only from figures the provider confirmed — a
successful answer or a content refusal, both of which are paid for; it contains no request or response
text.

**Lifecycle:** append-only, kept indefinitely; pruning the usage log is not in this iteration's scope.

### 4.5 `IdempotencyRecord`

It lives in process memory, not in the database (B-9) — which does not affect it being an entity: it
has an identity (client + key), a state machine and an irreversibility invariant, and the storage is
expressed as a port with an in-memory adapter.

| Field | Type | Note |
|---|---|---|
| `key` | `IdempotencyKey` | |
| `client_id` | `ClientId` | different clients' keys never collide |
| `state` | an enumeration | `in_flight` or `completed` |
| `usage` | `Usage \| None` | filled in on completion |
| `expires_at` | `datetime` (UTC) | `created_at` + `IDEMPOTENCY_KEY_TTL` |

**Invariants:** the only state transition is `in_flight → completed`, with no way back; the answer's
text is not stored in the record — a repeat on that key gets a conflict, not the result (§3.7.1).

**Lifecycle:** created when a request with a key is accepted, closed on completion, and gone when the
TTL expires or with the process. The protection holds within the life of a process and on one
instance — which is enough for the case "the caller dropped on a timeout, the service is alive"; a
restart aborts the generation itself, so there is nothing left to remember.

### 4.6 Transient objects of a single call

`Generation` is the result of calling a provider: the text, `Usage` and a `FinishReason`. It has
neither identity nor a lifecycle, is stored nowhere, and exists only inside a call. It carries neither
provider nor model: the answer comes from the model the call named, which the caller already holds, so
a second copy would be a second source for one fact — and a vendor's own model string, a dated version
of it, is not the registry's identifier anyway. The `downgraded` and `failed_over` markers are not part of it: the provider does not
know them, the use case does, and it adds them to the result on its own side. No separate "normalised
request" entity is introduced — the use case's input is described by a command DTO (§8.2).

---

## Stage 5. Use Cases

There is exactly one use case, and that is not an omission: everything else that might pass for one —
resolving an alias, checking the budget, retries, failover, usage accounting — are steps of one
scenario rather than scenarios of their own with their own actor and result. Operations for reading
spend are not in this iteration's scope (E-4).

### UC-L1. Generate an answer

- **Actor:** Caller
- **Input:** `client_id: str`, `subject: str`, `request_id: str`, `model: str` (an alias or a model
  identifier), `system: str`, `messages: list[(role: str, text: str)]`, `max_tokens: int | None`,
  `temperature: float | None`, `stop: list[str] | None`, `idempotency_key: str | None`
- **Output:** `text: str`, `input_tokens: int`, `output_tokens: int`, `provider: str`, `model: str`,
  `finish_reason: str`, `downgraded: bool`, `failed_over: bool`, plus `attempts: int`,
  `provider_timeouts: int` and `provider_ms: int` — not part of the response, but what the
  completion event reports (§8.4)
- **Flow:** resolves `model` to the candidate models that may answer it and rejects unknown ones;
  checks the idempotency key, the context against `max_context`, and the pre-flight time estimate;
  compares against the caller's and the provider's budgets, applying the `reject` or `downgrade`
  policy; calls the candidates with retries and, once the attempts are exhausted, the next candidate;
  on a confirmed response it writes the usage record, then returns the text together with the
  **actual** provider and model.

The order of the checks is fail-fast and cheapest-first: resolve the model → idempotency → context →
pre-flight → budget → call the provider. Anything that can be refused without reaching outside is
refused without it; writing the usage record is the last action and happens only on success.

---

## Stage 6. DB Schema

Postgres 16. **Only the usage log** is persistent. The budget's state is derived from it (§6.1). The
registry of providers and models comes from git config (§3.6, B-8); the rate-limit counters and the
idempotency keys live in process memory (B-9); prompts and answers are stored nowhere (§3.5).

```sql
-- The usage log: one row per provider call with confirmed usage — an answer, or a content refusal.
-- Append-only: the contract provides for neither updates nor deletions. The database does not forbid
-- them — the app role holds ordinary DML grants — so the rule is the port's contract (§8.0).
-- It is also the source of truth for the budget: spend in a window = an aggregate over this table.
CREATE TABLE usage_records (
    id            uuid        PRIMARY KEY,
    request_id    text        NOT NULL,   -- X-Request-ID: correlation with the logs, not the identity
    client_id     text        NOT NULL,
    subject       text        NOT NULL,
    provider      text        NOT NULL,
    model         text        NOT NULL,
    input_tokens  integer     NOT NULL,
    output_tokens integer     NOT NULL,
    latency_ms    integer     NOT NULL,
    downgraded    boolean     NOT NULL,
    failed_over   boolean     NOT NULL,
    created_at    timestamptz NOT NULL,
    CONSTRAINT ck_usage_records_tokens_non_negative  CHECK (input_tokens >= 0 AND output_tokens >= 0),
    CONSTRAINT ck_usage_records_latency_non_negative CHECK (latency_ms >= 0)
);

CREATE INDEX ix_usage_records_client_id_created_at ON usage_records (client_id, created_at);
CREATE INDEX ix_usage_records_provider_created_at  ON usage_records (provider, created_at);
```

### 6.1 The budget is computed, not stored

What has been spent in the current window is an aggregate over the usage log:

```sql
SELECT coalesce(sum(input_tokens), 0), coalesce(sum(output_tokens), 0)
  FROM usage_records
 WHERE client_id = :client_id
   AND created_at >= :window_start;
```

`:window_start` is midnight UTC of the current day, computed by the service and bound as a parameter
rather than derived from the database's `now()`: the same value becomes `Budget.window_start` and
its `resets_at`, so the aggregate and the `Retry-After` agree by construction, whatever time zone
the session runs in.

The caller's two pools do not overlap: the `client` scope adds `AND NOT downgraded`, the
`client_downgrade` scope `AND downgraded` (US-L06); the `provider` scope aggregates symmetrically by
`provider` over all rows. The queries are served by the existing indexes — the `downgraded` filter is
applied within the same index range — and read only the current day's rows.

No separate counter table is introduced: it would be a denormalised sum of this same table. It would
not give atomic budget reservation either — the check happens before the provider call and the
increment after it, so concurrent generations exceed the ceiling identically in both designs
(overspend within a single call is accepted explicitly, §1.3.3). A lazy window reset falls out for
free: a new day is a new filter range, and there is nothing to zero. Materialising the counters is
extension E-5, and it is switched on from a measurement rather than in advance.

### 6.2 The decisions behind the schema

| Decision | Why |
|---|---|
| Providers and models are not in the schema | B-8: the registry is reviewed configuration, not data. In the log they sit as strings because that is a historical fact: a model may have been removed from the config, and the record has to stay readable |
| The log carries the actual provider and model | what was requested is recoverable from the logs, while the money was spent on what actually answered; `downgraded`/`failed_over` show that the requested and the actual diverged |
| Idempotency keys are not in the schema | B-9: they protect against double payment while the process is alive; a restart aborts the generation itself, and there is nothing left to remember |
| Indexes on `(client_id, created_at)` and `(provider, created_at)` | the two dimensions in which spend is asked about: "how much did the caller spend" and "how much went to the provider". They also serve the budget check |
| Constraint and index names follow the schema's naming convention (`pk_`/`ck_`/`ix_` + table + columns) | a table built by a migration and one built from the schema in a test get the same names, so a later migration has a name to drop. No index is descending: Postgres reads a B-tree in both directions |
| The usage log is not pruned | it is the entire history of spend; pruning and aggregating completed days is a question that will arise together with E-5 |

### 6.3 How the schema serves the operations

| Operation | What happens in the database |
|---|---|
| Checking the budget | an aggregate over an index per checked scope for the current day: the caller's own pool and the provider, plus the caller's downgrade pool and the targets' providers when the policy moves the request. A later candidate's provider is read only when failover happens or the providers before it are out of budget, so the ordinary call stays at two aggregates |
| A call with confirmed usage — an answer, or a content refusal | one `INSERT` into the usage log |
| A call that produced no confirmed usage | nothing: no row, no counter |
| Accepting and completing a request with an idempotency key | no database access — the key's state is in process memory |

Migrations are Alembic, with file names `YYYYMMDD_HHMM_<slug>.py`.

---

## Stage 7. API Contracts

### 7.0 Conventions

| What | Value |
|---|---|
| Base path | `/api/llm-client` (the segment is the service's name, per the framework specification) |
| Authorization | `Authorization: Bearer <jwt>` on every route except `GET /api/llm-client/health`; the contract accepts no provider keys |
| Tracing | `X-Request-ID` is a **mandatory** incoming header; it is logged and returned in the response. Its absence is a contract violation, not a reason to generate one: every normal entry path sets it unconditionally, so an empty slot means a caller that bypassed the gateway. The answer is `422 MalformedRequestError` |
| Idempotency | the optional `Idempotency-Key` header |
| Format | `application/json` |
| Time | ISO 8601 in UTC |
| Error envelope | `{ "error": { "code": "...", "message": "...", "details": { ... } } }` from `holahost-http`. `code` is the error class's name; `message` is on the wire but is not in the published schema |
| Schema | `docs/openapi.json` is generated from the application and committed; CI regenerates it and compares by diff (`make openapi-check`). The security scheme is declared by `holahost_http.bearer_scheme` — it declares but does not enforce: authentication answered long before dependencies were resolved |

### 7.1 The endpoints

| Method and path | Purpose | Use case | Success |
|---|---|---|---|
| `POST /api/llm-client/generate` | generate an answer | UC-L1 | `200` |
| `GET /api/llm-client/health` | readiness | — | `200` |

There is one endpoint, matching the number of use cases. Reading one's own spend arrives with E-4.

### 7.2 Generation

```
POST /api/llm-client/generate
Idempotency-Key: 7c1f…            # optional

{
  "model": "quality",              // an alias from the config, or a model identifier
  "system": "You are …",
  "messages": [
    { "role": "user", "content": "A guest asks: what time is check-in?" }
  ],
  "max_tokens": 800,               // optional; 1..MAX_OUTPUT_TOKENS, larger is truncated to it
  "temperature": 0.3,              // optional; 0..1
  "stop": ["\n\n"]                 // optional; up to MAX_STOP_SEQUENCES (4), none empty
}

200 OK
{
  "text": "Check-in is from 15:00 …",
  "usage": { "input_tokens": 1240, "output_tokens": 310 },
  "provider": "anthropic",
  "model": "claude-haiku-4-5",
  "finish_reason": "stop",
  "downgraded": true,
  "failed_over": false
}
```

`system` is a field of its own rather than a message with the `system` role in the common list. That
is the guarantee from §3.8: the service is obliged to preserve the role boundary the caller set, and a
separate field makes that boundary indestructible — it becomes impossible to glue an instruction
together with untrusted data by mistake. It is optional and defaults to empty, which sends no system
block (§3.2). In `messages`, only the `user` role is allowed; `assistant` arrives with a multi-turn
conversation (E-6). A message's text is `content` on the wire, the name vendors use; the application
calls it `text`, and the router maps one to the other.

The request schema publishes types, not ranges: the use case judges every field itself (§7.4,
`InvalidPayloadError`), and a bound declared in the schema too would answer one fault with two
different `details.field`s. A field unknown to the schema is refused rather than ignored — a misspelt
`max_token` would otherwise be served with the default the caller meant to change. `temperature` is
bounded to 0..1, the range every configured vendor accepts, and `stop` to four non-empty sequences:
outside them a vendor rejects the request, which this service answers `500` and fails over on, for a
mistake the caller can fix.

`provider` and `model` in the response are the **actual** ones. If they diverged from what was
requested, that is visible through `downgraded` (the budget policy fired) and `failed_over` (a
provider switch fired); a caller that cares which model answered must read the response rather than
rely on the request.

The ceiling on an answer is published here, in the description of the request schema's
`max_tokens`, and that is where a caller reads it: `MAX_OUTPUT_TOKENS` is the documented maximum, a
larger value is truncated to it — so the schema carries no upper bound, which would refuse it
first — and the response carries no field saying so. A value below 1 is refused with `422 InvalidPayloadError` instead —
truncating it would mean answering a request nobody asked for, and passing it on buys a vendor's
rejection for a mistake the caller can fix.

### 7.3 Health

```
GET /api/llm-client/health          # no authorization

200 OK   { "status": "ok" }
503      { "status": "unavailable" }
```

Under the base path, like everything else: the gateway routes `/api/<svc>/*` without rewriting the
path, so a bare `/health` is unreachable from outside and the rollout's smoke check would never get to
it. It is the only public route, it is the one declared in the authentication middleware's
`public_paths`, and that same declaration exempts it from the `X-Request-ID` requirement.

What is checked is that the usage-log database is reachable. Health makes no provider calls: it must
neither spend money nor fall over together with a vendor. The `503` body names no reason; the reason
goes to the log as a `health_unavailable` warning.

### 7.4 Errors

An error's identity is **its class's name** (`PlatformError.code` returns `type(self).__name__`),
rather than a separate string taxonomy alongside it. A second, hand-maintained layer of names would be
a second source of truth: renaming a class would stop being a change to the contract, and the
divergence would surface at the caller. The classes are already named correctly in §8.2 and §8.3, and
those same ones are listed here.

The status is a projection of the identity, not a separate fact: the "error → status" table lives as a
single declaration in the code (`interface/http/errors.py`) and is passed into `create_edge_app` as
data.

**The service's own errors:**

| Class | HTTP | When | `details` | Retryable? |
|---|---|---|---|---|
| `UnknownModelError` | 400 | the alias or model resolves to no model of an enabled provider | `requested`, `available_aliases` | no |
| `ContextOverflowError` | 422 | the input estimate plus `max_tokens` exceeds the model's `max_context` | `max_context`, `estimated` | not until the input or `max_tokens` is reduced |
| `RequestTooSlowForSyncError` | 422 | pre-flight: a full answer does not fit one attempt's time, or the time ran out before an attempt could start (§3.7.1). Both are measured against the model the caller asked for, even where a downgrade had already switched the candidates — the advice has to be about the request that was made | `max_tokens_allowed`, `budget_seconds` | not until `max_tokens` is reduced |
| `DuplicateRequestError` | 409 | the `Idempotency-Key` is already in flight or already completed | `state` (`in_flight`/`completed`) | no |
| `BudgetExhaustedError` | 429 | a ceiling is exhausted and the request cannot be served (US-L05, US-L06); `Retry-After` is mandatory: the whole seconds until `resets_at`, rounded up, at least 1 | `scope` (`client`/`client_downgrade`/`provider`), `resets_at` (ISO 8601) | yes, after `resets_at` |
| `ContentRefusedError` | 422 | the model declined to answer this content | `provider`, `model` | no — the same content is refused again |
| `UpstreamLlmError` | 502 | every candidate model failed transiently, or the time ran out between failures | `attempts`, `upstream_status` (`null` on a timeout) | yes |

`ContentRefusedError` is a `422` rather than a `502`: the vendor answered, and what could not be
processed is the caller's content. `provider` and `model` name the one that refused, which after a
downgrade or a failover is not the one asked for. The call is paid for, so it produces a usage record
like any other confirmed spend (§4.4), and the tokens charged reach the completion event (§8.4).

What an error owes beyond its body, and what it reports to the log, are declared on the error itself:
`headers()` — the `Retry-After` of `BudgetExhaustedError` — and `log_fields()`, the completion-event
fields the response must not show. The `holahost-http` handlers write both; the headers only where the
error is answered as itself, the fields also for an error answered `500`.

`RequestTooSlowForSyncError` also answers a request whose time ran out on slow budget reads before
the first attempt could start: an overloaded database then looks like a request too large for the
synchronous mode, with a `max_tokens_allowed` down to 0. It is not told apart deliberately — the
reads would have to eat most of the time budget, and so rare a case is not worth an error of its
own.

A request the vendor itself rejects — a revoked key, a model missing at the vendor, a call the adapter
built wrong — publishes no error of its own: the cause is this service's, the caller can do nothing
about it, and it is answered `500 InternalError` with the reason in the log. The 5xx alarm is then
measuring what it is meant to (Metrics). Every deliberate pass-through of §8.3 — that rejection and
the three storage failures of a budget read — is listed in the edge's `silent_500_types`, together
with the domain's invariant violation: none is a `PlatformError`, and unlisted they would reach
Starlette's re-raising handler and print a traceback outside the JSON log.

**Platform responses** are produced by the edge rather than by this service, and they are the same
behind every service on the platform. They are deliberately absent from the table above: describing
one fact in N documents turns it into N facts that drift apart.

| Class | HTTP | Where from |
|---|---|---|
| `MalformedRequestError` | 422 | `RequestIdMiddleware` — `X-Request-ID` is missing |
| `InvalidPayloadError` | 422 | a rejected field. The use case judges the ranges — the schema publishes only types (§7.2) — so each rule answers with one `field`: `messages` (empty, an unknown role, a blank message), `max_tokens` below 1 (`limit` 1000; a value above `MAX_OUTPUT_TOKENS` is truncated), `temperature` outside 0..1, `stop` over four sequences or with an empty one (`limit` 4), `idempotency_key` outside 1…128 (`limit` 128). The framework's validation answers only a wrong type, a missing field or an unknown one, with the field's own name and `limit` null. `details` carries `field`, `limit` |
| `PayloadTooLargeError` | 413 | `BodySizeLimitMiddleware` — the body exceeds the transport ceiling |
| `RateLimitExceededError` | 429 | `RateLimitMiddleware` — the per-caller limit was exceeded; `Retry-After` comes from the exception |
| `InternalError` | 500 | anything not in the service's contract: the envelope with empty `details`, the reason only in the log |

`InvalidPayloadError` answers `422` rather than `400`: by RFC 9110 §15.5.1 a `400` is broken syntax or
framing, while by RFC 4918 §11.2 a `422` is a syntactically valid request whose content could not be
processed. `400` is left for a genuine framing violation; `UnknownModelError` holds it legitimately —
that is not the request's form but a non-existent reference inside it.

Every service is obliged to publish `InvalidPayloadError`: `register_error_handlers` refuses to
register without it, because the framework's validation rejects a request before any route is
entered — including on a path or query parameter, so a service with no request bodies is no exception.

Two different refusals answer `429` and are distinguished by class rather than by status:
`RateLimitExceededError` means "too often, wait some seconds", `BudgetExhaustedError` means "the money
for today has run out, wait for the window to reset". They must not be merged: the caller's reactions
differ.

`401` and `403` have no body with a code. Vendor codes and provider messages are passed through in no
case — they stay in the logs together with the number of attempts.

The published schemas are assembled from `holahost_http.error_schemas` (`envelope()`, the discriminator
on `code`, `INTERNAL_RESPONSES`, the strict `Strict` base); the service declares only the bodies of its
own errors.

---

## Stage 8. Detailed Sequence Flow

### 8.0 Ports

```python
class ProvidersRepo(Protocol):
    def resolve(self, model_ref: str) -> list[Model]: ...    # ordered candidates: an alias expands
                                                             # to its chain, a model id to that
                                                             # model alone; empty — nothing resolves
    def downgrade_targets(self) -> list[Model]: ...          # the policy's cheaper models, in order
    def aliases(self) -> list[str]: ...                      # what an unknown model is answered with
    # raises: —  (the registry is loaded and validated at startup; after startup it is read-only)
    # concurrency: immutable after startup, so any thread of the pool reads it without locking

class GenerationProvider(Protocol):
    def generate(self, model: Model, *, system: str, messages: list[Message],
                 max_tokens: int, temperature: float | None, stop: list[str] | None,
                 timeout_s: float, request_id: str) -> Generation: ...
    # Generation = (text: str, usage: Usage, finish_reason: FinishReason) — the model that answered
    #              is the one the call named, so it is not returned a second time (§4.6)
    # request_id: the request's X-Request-ID, propagated to the vendor where its protocol allows
    #             it (US-L13); there is no request-scoped context an adapter could read it from.
    #             `anthropic` takes no caller-chosen identifier it would record, so there it stays
    #             in this service's own log lines
    # timeout_s: the wait for the answer — what pre-flight measured the generation against; setting
    #            up the call is bounded apart, briefly, by the adapter (§3.7)
    # raises: TransientProviderError (429, 5xx, overload, a timeout — retryable; carries the vendor
    #           status, absent on a timeout, and its Retry-After when it sent one),
    #         ProviderRejectedRequestError (the vendor refused the request itself: a revoked key, a
    #           model it does not know, a call the adapter built wrong — the cause is this service's
    #           and specific to that vendor, so another candidate may still answer),
    #         ProviderRefusedContentError (the model declined this content; carries the usage the
    #           provider confirmed, because the call was paid for)
    # concurrency: implementations must be thread-safe — one instance per process, called
    #              concurrently from the request thread pool

class BudgetRepo(Protocol):
    def client_state(self, scope: Literal[BudgetScope.CLIENT, BudgetScope.CLIENT_DOWNGRADE],
                     client_id: ClientId) -> Budget: ...
    def provider_state(self, provider: ProviderName) -> Budget: ...
    # Two methods rather than one with a scope and a string key: the key's type follows from the
    # scope, and a mismatch is then a type error rather than an invariant violation at runtime.
    # raises: StorageUnavailableError, ConcurrentUpdateError,
    #         IntegrityError (the app role lacks the grant to read the log — a deploy defect;
    #           holahost-db classes a privilege refusal with the integrity violations)
    # lock: **deliberately not taken** — the subject cannot be held for the duration of a generation,
    #       which takes seconds. Hence the accepted overspend within a single call (§1.3.3): two
    #       simultaneous generations will both see the remainder and both spend it

class UsageRepo(Protocol):
    def add(self, record: UsageRecord) -> None: ...
    # raises: StorageUnavailableError, ConcurrentUpdateError, IntegrityError
    # concurrency: the insert is idempotent by the record's `id` (implemented as `ON CONFLICT DO NOTHING`).
    #              Re-inserting the same record is the ordinary redelivery case rather than an error,
    #              so a key conflict never surfaces as IntegrityError; that type stays declared for a
    #              CHECK the entity should have prevented — a defect.
    # lock: not needed — an append-only log, with no competing row updates

class IdempotencyStore(Protocol):
    def begin(self, client_id: ClientId, key: IdempotencyKey) -> None: ...
    def complete(self, client_id: ClientId, key: IdempotencyKey, usage: Usage) -> None: ...
    def release(self, client_id: ClientId, key: IdempotencyKey) -> None: ...
    # raises: begin — DuplicateRequestError (carrying the in_flight/completed state);
    #         complete, release — —
    # concurrency: `begin` is an atomic claim of the key (compare-and-set) against the other threads
    #              of the pool; the check and the claim are not separated, or two parallel repeats
    #              would both pass and pay for the generation twice. One lock guards all three.
    #              A record past its TTL counts as absent, and a key no longer held is ignored by
    #              `complete` and `release` alike

# RateLimiter — there is no port in this layer: both it and its in-memory implementation live in
# holahost_http. The middleware calls the limiter before the use case is entered (§8.1), so no port
# of the application layer sees it. The service declares only the values: its buckets and the
# ceilings per (bucket, is_service). The platform port's signature is keyword-only:
#     check(*, client_id: str, subject: str, bucket: str, is_service: bool) -> None
#     raises: RateLimitExceededError (carrying retry_after)
# is_service is passed in rather than derived from subject == client_id inside the limiter: that is a
# fact about the token model, and its owner is holahost-auth.
```

`ProvidersRepo` reads the git config loaded at startup; `IdempotencyStore` is implemented in process
memory; `BudgetRepo` and `UsageRepo` go to Postgres.

The signatures follow the project's shared convention: a query returns an object, `None` or a list; a
command returns `None` and expresses a refusal with a typed exception; a boolean result is not used.
That is why `begin` and `check` raise rather than returning a refusal flag — the exception carries the
context the calling code would have needed anyway: the duplicate's state, the time until the limit
resets.

`UnitOfWork` and the three storage-failure types (`StorageUnavailableError`, `ConcurrentUpdateError`,
`IntegrityError`) come from `holahost-db` and are not re-declared here — the contract and the
translation of vendor errors are shared platform-wide.

Every method declares its `raises`; an implementation raises nothing beyond what is declared, and the
calling code is obliged either to handle what is declared or to pass it up deliberately. The storage
failures are split by reaction, and all three reach this service. `ConcurrentUpdateError` does
although there are no competing row updates here: `holahost-db` sets a statement timeout
and classes a cancelled statement with lock-wait timeouts, so a budget aggregate or an insert that
outran the timeout arrives as that type. The use case passes it up from a budget read — repeating a
five-second aggregate would spend the request's time budget — and retries the transaction around the
usage record, whose insert is idempotent and whose spend is already paid for. `IntegrityError` stays a
defect: on the usage record a `CHECK` the entity should have prevented, on a budget read a missing
grant. Methods working with shared state also declare a concurrency contract: it states a business
requirement ("a duplicate does not pass twice", "overspend within a single call is accepted"), while
the mechanism that enforces it is the implementation's choice.

### 8.1 The common outline of a request

The edge is assembled by `holahost_http.create_edge_app`: the service passes in *what* runs and the
factory decides the order (framework specification, "The order of the HTTP edge's middleware"). The
resulting stack, outermost first:

1. `RequestIdMiddleware` — reads `X-Request-ID`, starts the timer, echoes the header back; its
   absence → `422 MalformedRequestError`. Outermost, or a refusal at any later step would be left
   without the caller's identifier.
2. `BodySizeLimitMiddleware` — `413 PayloadTooLargeError` by `Content-Length`, **before the body is
   read**. Here, rather than at parse time: the framework reads the body while assembling the
   handler's arguments, that is, before resolving its dependencies — a check expressed through
   `Depends` accepts the whole request and only then refuses it. The transport ceiling is
   `MAX_INPUT_BYTES` itself, over the whole body: nothing inside the body is measured in bytes again,
   so there is no inner limit to derive it from or to advertise instead.
3. `HolahostAuthMiddleware` — `401` on failure; the only thing that puts the token into `scope`.
4. `RateLimitMiddleware` — `429` + `Retry-After` when exceeded; keyed by the token from step 3.
5. Routing → `interface/http/schemas.GenerateRequest`: parsing the body and the `Idempotency-Key`
   header; a wrong type, a missing or an unknown field → `422 InvalidPayloadError`. The route attaches
   `requested_model` to the request's completion event (`holahost_http.add_log_fields`) before the use
   case runs, so a refusal's event names it too.
6. `GenerateUseCase.execute(cmd)`.
7. The `holahost_http` exception handlers — an application error → a status, an envelope and the
   headers it owes per the service's `ERROR_CONTRACT`; a domain exception no use case translated, and
   every deliberate pass-through of §8.3 → `500` with empty `details`, through `silent_500_types`
   (framework specification, "Brief: domain exceptions"). The event they write carries the error's
   `log_fields()` and the route's fields.

### 8.2 UC-L1 "Generate an answer"

`GenerateUseCase.execute(cmd: GenerateCmd) -> GenerateResult`
`GenerateCmd = (client_id, subject, request_id, model_ref, system, messages, max_tokens, temperature, stop, idempotency_key)`

`request_id` is the request's `X-Request-ID`; the generation's own identifier is generated by
`UsageRecord.create` (step 1.10).

| # | Module and call | What happens |
|---|---|---|
| 1.0 | `deadline = monotonic() + RETRY_TOTAL_BUDGET` | one deadline for the whole request, budget reads, pauses and failover included |
| 1.1 | the command's fields become domain values | an unknown role, an empty `messages`, a blank message, `max_tokens < 1`, a `temperature` outside 0..1, a `stop` over four sequences or with an empty one, or a key outside 1…128 → `InvalidPayloadError` naming the field |
| 1.2 | `ProvidersRepo.resolve(cmd.model_ref) -> list[Model]` | empty → `UnknownModelError` with `ProvidersRepo.aliases()`; the first candidate is the one to call, the rest are for failover |
| 1.3 | `IdempotencyStore.begin(client_id, key)` | only if a key was sent; on a duplicate it raises `DuplicateRequestError` with the state (`in_flight`/`completed`) |
| 1.4 | `max_tokens = min(cmd.max_tokens or model.max_output, MAX_OUTPUT_TOKENS, model.max_output)` | computed per model: a downgrade target or a failover candidate may have a lower ceiling of its own |
| 1.5 | `estimate_input_tokens(system, messages) + max_tokens` → compared against `model.max_context` | exceeding it → `ContextOverflowError` |
| 1.6 | `max_tokens / model.tokens_per_second` → compared against `min(time left, PROVIDER_TIMEOUT)` | does not fit → `RequestTooSlowForSyncError` |
| 1.7 | `BudgetRepo.provider_state(provider)` of the first candidate, then `BudgetRepo.client_state("client", client_id)` | one short transaction; the first candidate's provider out of budget is passed over as in failover — the next candidates' providers are read until one can serve — and only when none is left → `BudgetExhaustedError` on `provider`, whatever the policy |
| 1.8 | the caller's own budget exhausted: under `reject` → `BudgetExhaustedError`; under `downgrade` → `BudgetRepo.client_state("client_downgrade", client_id)`, then `ProvidersRepo.downgrade_targets()` without the request's own candidates, filtered by steps 1.5, 1.6 and each target's provider budget | the pool exhausted → `BudgetExhaustedError` on `client_downgrade`; no target left → `BudgetExhaustedError` on `client`, because the caller never asked for the cheaper model and its limits are not the caller's to fix |
| 1.9 | a loop over the candidates: `GenerationProvider.generate(model, …, timeout_s=min(time left, PROVIDER_TIMEOUT)) -> Generation` | an attempt starts only while a full answer still fits the time left; `TransientProviderError` → a repeat with backoff within `RETRY_MAX_ATTEMPTS` per candidate; a rejected request → the next candidate at once; a candidate that does not fit is passed over; candidates exhausted → `UpstreamLlmError`, or the rejection itself when no transient failure happened |
| 1.10 | `UsageRecord.create(request_id, client_id, subject, provider, model, usage, latency, downgraded, failed_over)` | for an answer and for a content refusal alike — both are paid for; the record's `id` is generated here |
| 1.11 | `with UnitOfWork(): UsageRepo.add(record)`, retried on `ConcurrentUpdateError`; then `IdempotencyStore.complete(...)` | the key is completed once the spend is fixed or its write has failed; a write failed for good → `UsageNotRecordedError`; a failure before that → `IdempotencyStore.release(...)`, and no usage record |
| 1.12 | `GenerateResult(text, usage, provider, model, finish_reason, downgraded, failed_over, attempts, provider_timeouts, provider_ms)` | `attempts`, `provider_timeouts` and `provider_ms` feed the completion event (§8.4), not the response |

The checks run cheapest-first (§5): everything that can be refused without reaching outside is refused
before the provider is called. Writing the usage record is the last action, and only a call the
provider confirmed usage for reaches it.

### 8.3 Handling the declared exceptions

| Port exception | Who handles it | How |
|---|---|---|
| `DuplicateRequestError` | the use case | translates it into `409 DuplicateRequestError` with the state from the exception |
| `TransientProviderError` | the use case, step 1.9 | a repeat with backoff, then the next candidate; exhaustion → `502 UpstreamLlmError` |
| `ProviderRefusedContentError` | the use case, step 1.9 | no repeat and no failover — the cause is the content, not the vendor. The confirmed usage is recorded, then `422 ContentRefusedError` |
| `ProviderRejectedRequestError` | the use case, step 1.9 | no repeat; the next candidate at once, because the cause is this service's key, adapter or config at that one vendor. Every candidate rejecting it is a defect: the exception passes through and is answered `500` with the reason in the log |
| `StorageUnavailableError` / `ConcurrentUpdateError` / `IntegrityError` on a budget read | **a deliberate pass-through** | outward a `500`. Skipping the check and generating anyway is not an option: without the budget check the call would mean unaccounted spend, and repeating a five-second aggregate would spend the request's time budget. `IntegrityError` here is a missing grant, a deploy defect |
| `ConcurrentUpdateError` on `UsageRepo.add` | the use case, step 1.11 | the transaction is retried — the insert is idempotent by the record's `id`, and the generation is already paid for, so losing the record is the worst outcome. The retry is bounded by its count (three attempts) and by each attempt's own timeouts — a 2 s lock wait, a 5 s statement — not by the request's deadline: the caller loses the text whatever happens next, and stopping at the deadline would lose the record as well. Generations compete for no row here — the log is append-only and every `id` is fresh — so what raises it is a table held by DDL or maintenance, or an overloaded database. Past the retries it is handled as the row below |
| `StorageUnavailableError` / `IntegrityError` on `UsageRepo.add` | the use case, step 1.11 | raised as `UsageNotRecordedError`, carrying the spend the provider confirmed, with the storage failure as its cause; outward a `500`, even though the generation has already been paid for. Returning the text with the spend unsaved is worse: it silently breaks the accounting. The error reports the carried figures as its completion-event fields, which the platform's handler writes into `op_completed` (§8.4), so the spend reaches the event log even when it misses the usage log |
| `RateLimitExceededError` | the platform middleware, before the use case | `429` + `Retry-After` from the exception; the refusal event is written by `holahost_http.log_rejection` |

Separately, the fate of the idempotency key after a successful `begin`: it is **released** while
nothing has been paid for, or the key would stay `in_flight` until its TTL expired and block an
honest repeat. Once a provider has charged — an answer or a content refusal — it is **completed**
instead, including when writing the usage record then failed: a released key would let the repeat buy
the same answer a second time, which is exactly what the key exists to prevent.

### 8.4 The operation-completion event

A metric is a structured log event; the aggregation is defined on the log-collection side (Stage 11).
The event's name, the core of its fields (`request_id`, `client_id`, `sub`, `route`, `outcome`,
`duration_ms`, `error_reason`) and the levels are a **platform contract** — see the framework
specification, "The operation-completion event contract". Here there is only what this service adds
beyond the core; the metrics themselves are collected in the "Metrics" section after the backlog.

```
op_completed { <the platform core>,
               requested_model, provider, model,
               input_tokens, output_tokens,
               provider_ms, attempts, provider_timeouts,
               downgraded, failed_over, preflight_rejected }
```

`provider_timeouts` counts the attempts cut off by the service's own timeout — calls most likely
charged whose spend never reaches the usage log (B-12). A failed connection counts too, since it
carries no status either: it is not charged for, so the figure runs slightly high, but it is the
rarer of the two. It comes from the result, or from
`UpstreamLlmError`, which carries it outside its published `details`. For a request whose usage
record could not be written, `input_tokens`, `output_tokens`, `provider` and `model` come from
`UsageNotRecordedError`: once the write has failed, it is the only place the confirmed spend
survives. A content refusal was charged too, so `ContentRefusedError` reports the same four;
`preflight_rejected` is `RequestTooSlowForSyncError`'s.

Who writes which line: the route writes the success line; a refusal's line is written by the
`holahost-http` exception handler, which takes these fields from the error (`log_fields()`) and
`requested_model` from what the route attached before the use case ran (§8.1). Both are assembled by
`holahost_http.log_completion`, so the core is built one way and `route` is the resolved path on
both — `POST /api/llm-client/generate` — and one filter on it counts every outcome.

The route's `429` has two bodies, discriminated by `code`: this service's `BudgetExhaustedError` and
the platform limiter's `RateLimitExceededError`, which the document names beside it for that reason
alone (§7.4).

The service's own fields are declared as a list in `config/logging.py` and passed to
`configure_logging`; the core comes from `holahost-observability` and is not repeated here. Beyond
`op_completed`, the list carries `vendor_stop_reason`, for the adapter's warning about a vendor stop
reason outside its table (§3.2). Refusals
before routing — answered by middleware without entering the handler — are written by
`holahost_http.log_rejection`, so there is an event even for a request that never reached the use case.

`provider` and `model` are the **actual** ones: when they diverge from what was requested, the
`downgraded` and `failed_over` fields explain why. `requested_model` is kept alongside precisely for
that comparison.

The texts of `system`, `messages` and the answer, and the provider keys, never reach the events
(US-L13): a field name outside the allowlist fails the call rather than silently shortening the line.

---

## Stage 11. Infrastructure

The environments, the composition of the dev stack, the Terraform roots (`infra/common`,
`infra/envs/<env>`), state storage, working with secrets and the runbook requirements are the
framework specification's defaults, section "A service's infrastructure — the defaults". Only the
deviations and additions are here.

| Resource | The difference |
|---|---|
| **The database container** in the service's compose project | ordinary Postgres 16: the schema (§6) needs no extensions |
| **Secrets in SM** (`infra/envs/<env>`) | two kinds: the database password and **one secret per LLM provider**. The providers' secret names reach the registry's git config (§3.6) as references, while the values live only in SM. Adding a provider means both editing the config and creating the secret in the TF root |
| **Outgoing internet access** | the only service on the platform that needs it: calls to the providers' APIs. The network requirement is outgoing HTTPS to the providers' domains; when egress filtering appears, the domain list comes from the same registry |
| **Instance role rights** | beyond the default — reading the providers' secrets; this is the only role on the platform with access to them (B-2) |
| **Instance requirements** | no memory for models is needed — all the heavy work is at the vendor. The constraint is different: every generation occupies a thread for the whole wait, so the thread pool's size is the throughput ceiling (B-7) |
| **`infra/common`, ECR** | no difference: a call to the platform's `service-ecr` module with the service's name |
| **Alarms** (`infra/envs/<env>`) | the log group, the SNS topic, the `5xx` alarm and the filters for authorization and limit refusals come from the platform's `service-observability` module. Beyond it: the share of `UpstreamLlmError`, the utilisation of the daily budget, and the share of `downgraded` — the last of which catches the quiet degradation in quality that nobody would otherwise notice (B-4). They need to know the route and the domain fields, so they live in the service's root |
| **Runbook, the "Check" section** | the profile operation is a generation on a cheap model with a short `max_tokens`; look at `op_completed` in the logs. The check has to be cheap: it spends real money |
| **Runbook, an extra section** | rotating a provider's key: replace the value in SM, restart the container, run a control generation. No image rollout is required |

---

## Stage 12. CI/CD and conventions

Branches, commits, static analysis, pre-commit, the composition of the pipelines, the rollout strategy
and the repository settings are the framework specification's defaults, section "CI/CD and
conventions — the defaults". Only the deviations and additions are here.

| Item | The difference |
|---|---|
| **Tests in `ci`** | no test reaches a real provider: the adapters are checked with fakes, and the retries, failover, budget and pre-flight with scenarios on top of them. This is not only about money: a test that depends on a vendor becomes flaky for someone else's reasons |
| **Config validation** | a separate step: the registry of providers and aliases is checked by the same procedure as at service startup (US-L14). An error in the config has to fail in the PR, not at rollout |
| **Checking the secret references** | a step verifies that every `api_key_ref` from the config corresponds to a secret created by the environment's TF root. A divergence means a service that will not come up |
| **Smoke after the rollout** | a generation on the cheapest model with a minimal `max_tokens`. It is the only smoke check on the platform that **costs money** — it must not be put in a loop and must not be retried without a bound |
| **CI's access to provider keys** | the CI role has none and never gets any: only the instance role reads the keys (B-2). That is why the smoke check goes through the service itself rather than straight to the vendor |
| **The order in `deploy`** | no difference: migrations before the container comes up |
| **`Makefile`** | `include ../../make/common.mk` plus the service's name and the image size ceiling; the targets are shared |
| **The service skeleton** | copied from `holahost/templates/service` — the clean-architecture tree, the tooling, the test skeleton and the Terraform roots are already in place |
| **`openapi-check`** | the step exists: `docs/openapi.json` is regenerated from the application and compared by diff — a changed contract has to be seen in the PR |

---

## Stage 13. Backlog

### Shared libraries

Built within the scope of the `rag-documents` specification and mandatory for every subsequent service
(framework specification, "Reusable shared entities"). Here it is about consuming them, not building
them.

- `LIB-01` `holahost-auth` — JWT validation; `AuthConfig` reads its five variables from the
  environment itself, and the service sets only `EXPECTED_AUDIENCE`
- `LIB-02` `holahost-http` — the error envelope and `PlatformError`; the edge's middleware and their
  assembly by `create_edge_app`; `RateLimiter` and its in-memory implementation; the exception handler
  driven by the service's contract; the platform errors and the published schemas; `bearer_scheme`
- `LIB-03` `holahost-observability` — the JSON logger, the field allowlist mechanism, the core
  `op_completed` fields, the free-text scrubber
- `LIB-04` `holahost-db` — the three storage-failure types and the translation of vendor errors,
  `UnitOfWork` and its SQLAlchemy implementation, the engine factory, the settings of the two Postgres
  identities, role provisioning, the skeleton of `alembic/env.py`

### Backend — Domain

The service skeleton — a copy of `holahost/templates/service` — arrives with `L-01`–`L-03`.

- `L-01` Value objects — the identifiers, `Usage` as a pair of separate counters, `Message`,
  `IdempotencyKey`, `FinishReason`
- `L-02` Entities — `Provider`, `Model` (with the provider object inside it), `Budget`, `UsageRecord`,
  `IdempotencyRecord`
- `L-03` Domain exceptions

### Backend — Application

- `L-04` The ports of §8.0 — protocols with declared `raises` and a concurrency contract
- `L-05` The command and result DTOs for generation
- `L-06` Application exceptions — the errors the service publishes, plus the three the generation
  port raises; the "error → status" table belongs with the schemas and the edge, in `L-15`
- `L-07` UC-L1 — generation: resolving the model, idempotency, the context, pre-flight, the budget
  with its policy, retries, failover and usage accounting, in the declared order

### Backend — Infrastructure

- `L-08` Typed settings, loading the provider registry's git config and validating it at startup
- `L-09` The database schema and the first migration — the usage log with its indexes
- `L-10` Repositories — writing the log with an idempotent insert, and the budget's state as an
  aggregate over the window
- `L-11` The provider adapter over `langchain` — calling the model, normalising `finish_reason`,
  translating vendor errors into transient and permanent ones
- `L-12` An in-memory idempotency store with a TTL; the rate limiter is `InMemoryRateLimiter` from
  `LIB-02`, with the service declaring the buckets and the ceilings
- `L-13` Declaring the service's own event fields on top of the `LIB-03` core and calling
  `configure_logging`; the allowlist mechanism is the library's

### Backend — Interface

- `L-14` The FastAPI application, the router, the request and response schemas, the `Idempotency-Key`
  header
- `L-15` `ERROR_CONTRACT` with the published schemas of every error, the types answered `500` with
  empty `details` (the domain's invariant violation, the vendor's rejection of a request and the three
  storage failures of a budget read), the `Retry-After` a `BudgetExhaustedError` owes and the
  completion-event fields the errors carry — both through `LIB-02`'s `PlatformError.headers()` /
  `log_fields()` — and the values for the edge (the buckets, the body ceiling, the error for a missing
  `X-Request-ID`); the assembly is `create_edge_app` from `LIB-02`
- `L-16` `GET /api/llm-client/health`, with no provider calls
- `L-17` The composition root

### Infra

- `L-18` The Dockerfile and `docker-compose.yml` from the template, adapted — the application and
  Postgres with a volume
- `L-19` The `infra/common` TF root — ECR with a lifecycle policy
- `L-20` The `infra/envs/<env>` TF root — the database secret, the provider secrets, the log group, and
  alarms on upstream failures, budget utilisation and the share of `downgraded`
- `L-21` `docs/runbook.md` — the sections per environment plus the section on rotating a provider's key

### CI/CD

- `L-22` The trigger stub and the `ci` pipeline — hooks, tests on fakes, registry config validation,
  checking the secret references, `docker build`, `terraform plan`
- `L-23` The `deploy-staging` pipeline — apply, build and push, SSM with migrations and the rollout,
  the paid smoke check on a cheap model
- `L-24` The `promote-prod` pipeline — resolving the digest, migrations, the rollout, smoke, the
  approval gate
- `L-25` The Makefile from the template, adapted — lint, types, tests, `lint-imports`, `dev-up`,
  migrations and `ci-local` come from `common.mk`

---

## Metrics

The only source is the structured log event (B-13): there is neither a metrics agent nor Prometheus in
the topology, so **everything listed here is derived from the `op_completed` fields** — by a standing
filter where a number falls out of the line, and by a Logs Insights query over the same group where
unique values or a ratio of metrics are needed. The event's shape is §8.4.

The filters are split across two places, and the boundary runs along knowledge of the service: what is
derived from the `op_completed` core lives in the platform's `service-observability` module and is
written once for the whole platform; everything that matches a route, the identity of one of the
service's own errors, or a domain field lives in this service's `infra/envs/<env>/observability.tf`.
Every published metric has either an alarm or a dashboard widget: a filter with neither is spending on
a metric nobody will open.

The literals in the filters are a contract copied by hand: an error class renamed in the code and not
renamed in Terraform quietly stops matching, and `treat_missing_data = "notBreaching"` reads a dead
metric as health.

### Technical metrics

| Metric | Source | Where the filter lives | Alarm | Why |
|---|---|---|---|---|
| 5xx rate | `outcome = InternalError` or `5*` | the module | yes | the only class that is entirely the service's fault |
| p95 of generation duration | `duration_ms` | the service | yes | control of `GENERATION_P95_BUDGET` |
| Share of the provider's time | `provider_ms` ÷ `duration_ms` | the service | no | how much the service spends on top of the vendor; growth with `provider_ms` unchanged is a regression on our side |
| Generation success rate | metric math `success ÷ (success + failure)` | the service | yes | catches degradation that no single class of refusal shows |
| Share of upstream failures | `outcome = UpstreamLlmError` | the service | yes | exhaustion of the attempts and of the alias's candidates |
| Distribution of `attempts` | `attempts` | the service | no | the provider's health; steady growth is a reason to revisit `RETRY_*` |
| Provider timeouts | `sum(provider_timeouts)` over the period | the service | no | estimates the spend that bypassed the log (B-12); attempts at the maximum would count `429` and `5xx`, which cost nothing, as well |
| Pre-flight refusal rate | `preflight_rejected` | the service | no | a noticeable share means the synchronous mode has stopped covering the load — the trigger for E-3 |
| Authorization refusal rate | `outcome = 401` / `403` | the module | no | a spike means a caller is misconfigured |
| Limit refusal rate | `outcome = RateLimitExceededError` | the module | no | confirms that `RATE_LIMIT_*` is adequate |
| Budget refusal rate | `outcome = BudgetExhaustedError` | the service | no | a different refusal with the same `429`; it must not be mixed with the limit |
| Content refusal rate | `outcome = ContentRefusedError` | the service | no | prompts the models decline: spend that buys no answer, and a signal about what the callers are sending |
| Context and model refusal rate | `outcome = ContextOverflowError` / `UnknownModelError` | the service | no | growth means a caller is sending what the service does not accept: a drifted alias config, or unchecked input |
| Transport-contract violation rate | `outcome = MalformedRequestError` | the service | no | a non-zero value means a caller is bypassing the gateway |
| Process warm-up time | `startup_completed.duration_ms` | the service | no | explains a readiness dip after a rollout |

### Product metrics

| Metric | Source | Why |
|---|---|---|
| Generations per period | `outcome = success` | the basic measure of consumption |
| Token spend by caller, provider and model | `input_tokens`, `output_tokens`, `client_id`, `provider`, `model` | the basis of reporting and of budget forecasting |
| Budget utilisation | the window's spend against `BUDGET_CAP_*` | a warning before refusals start |
| Share of `downgraded` | `downgraded` | **quiet degradation in quality**: callers have long been getting a model other than the one they ask for, and cannot see it themselves |
| Share of `failed_over` | `failed_over` | the same about the provider; steady growth is a reason to revisit the chain |
| Share of requests where the actual model ≠ the requested one | `requested_model` ≠ `model` | both of the previous two as one number — how many answers came from something other than what was asked for |
| Average answer length | `output_tokens` | together with the spend, it answers what a typical answer costs |
| Unique callers per period | `client_id` | how many integrations actually use the service |

The last row and every ratio of metrics are **queries, not standing filters**: a CloudWatch filter
turns a matched line into a number and can neither count unique values nor divide one metric by
another. They are computed by a Logs Insights query over the same log group; that introduces no new
component, but no alarm can be attached to them either.

### What these metrics do not answer

- **The answer's quality.** No field says whether an answer was useful: texts never reach the events
  (US-L13). Judging quality by `finish_reason` or by length would be self-deception.
- **What was asked.** Prompts and answers are logged under no aggregation. That is the allowlist's
  price, and it is accepted deliberately.
- **How much money was spent, in currency.** The event carries tokens, not cost: the price list lives
  in the provider registry and changes without a rollout, so the conversion into money is done at
  reporting time rather than in the log.

---

## Extensions

The format of an entry: why and under what conditions → decision → what changes in the contract →
trigger. The extensions do not exist in code — no flags, no stubs.

Extensions shared by every microservice on the platform are kept in the framework specification,
section "Platform-wide extensions" (S-1 asynchronous execution, S-2 persistent rate-limit counters,
S-3 scaling, S-4 direct calls from the browser, S-5 local grants, S-6 introducing an ORM). Here there
is only what is specific to this service, including its delta to those shared entries.

### E-1. Streaming the answer

**Why.** The synchronous integration ceiling (30 s) cuts off long generations, and an interactive
consumer — a chat UI — needs the first token sooner than the whole answer.

**Decision.** SSE from the provider through to the caller, passing chunks end to end; `usage` arrives
in the final event, and the usage record is written after the stream completes. It requires streaming
support along the proxy chain (nginx: buffering disabled on that route; API Gateway: the path checked
separately).

**What changes in the contract.** A second response mode with a different content type; an error
occurring after the first chunk has been sent arrives inside the stream rather than as a response
code, and the caller is obliged to handle that.

**Trigger.** An interactive consumer (a chat UI) appears, or answers longer than `MAX_OUTPUT_TOKENS`
are needed.

### E-2. Tool use and structured output

**Why.** Orchestrators will need not free text but a function call or JSON to a schema — without it
every caller parses text with regular expressions.

**Decision.** Passing tool definitions and the structured-output mode through into the `generate`
contract; normalising the provider's response into one shape, "text, or a tool call with arguments".
Executing the tools stays with the caller — the service does not run them.

**What changes in the contract.** Optional fields with the tool definitions and the response schema;
the response gains a "tool call" variant with the same error taxonomy.

**Trigger.** The first Orchestration Service that needs a machine-parseable answer.

### E-3. Asynchronous generation (a delta to S-1 of the framework specification)

**Why here specifically.** The synchronous mode is bounded by the integration ceiling (§3.7): long
prompts, large `max_tokens` and batch scenarios do not fit into it, and the pre-flight refusal
(§3.7.1) only refuses them honestly. On top of that, the synchronous path loses an already-paid-for
result when the connection drops.

**The delta to the shared decision.** There is one task type — generation; the handler is idempotent
by the request's identifier, so that a redelivery does not produce a second provider call. The
specificity absent from S-1: **the service starts storing content** — both the prompt
and the answer have to sit in the database until they are collected. The property "neither the prompt
nor the answer is stored anywhere" (§3.5, §3.8) stops holding for the asynchronous path, and that is
the most expensive part of the extension: result TTLs, ownership of the result by `client_id`, and the
question of encryption at rest all appear.

**What changes in the contract.** The contract becomes two-phase: enqueue → identifier → read the
result. The budget is charged when the task completes, so a budget refusal becomes asynchronous and is
invisible to the caller at enqueue time. The synchronous mode's idempotency key (§3.7.1) is replaced
by full delivery of the result — a repeat stops being a conflict.

**Trigger.** The first caller whose request is consistently refused by the pre-flight check, or the
first batch scenario.

### E-5. Materialising the budget counters

**Why.** The budget check is two aggregates over the usage log for the current day (§6.1). That is
cheap while there are few rows in the window. Once there are hundreds of thousands, an aggregate on
every call starts to cost noticeably, and with several instances (S-3 of the framework specification)
a second motive appears — shared state.

**Decision.** A counter table `(scope, scope_key, window_start)` incremented with
`INSERT … ON CONFLICT DO UPDATE`, updated in the same transaction as the write to the usage log. The
usage log stays the source of truth: the counter is verifiably reconstructible from it, and a
divergence is a signal of a defect rather than a reason to fix the data by hand. The same step settles
the fate of the idempotency keys with several instances: a shared store instead of process memory.

**What changes.** Nothing in the contract; the specification gains a table and the requirement to keep
it consistent with the log.

**Trigger.** A measurement: the budget check becomes a noticeable share of `GENERATION_P95_BUDGET`, or
a second replica is introduced.

### E-4. Self-service on spend

**Why.** Today only an operator can see the spend and the remaining budget, through the database; a
caller would benefit from knowing the remainder before it gets a `429`.

**Decision.** Operations to read one's own spend over a period and the current window's remainder;
access strictly to one's own data, by the `client_id` from the token.

**What changes in the contract.** Read operations appear, and the policy "your own `client_id`, your
own spend only" becomes part of authorization.

**Trigger.** The second LLM-consuming service on the platform.

### E-6. Multi-turn conversation

**Why.** A chat assistant sends the history of a conversation, not a single question: the model has
to see its own earlier answers as its own turns.

**Decision.** The `assistant` role in `messages`, together with the turn-order rules the providers
impose — which role opens the list, that it closes on a `user` turn, how turns alternate — checked by
the service before the provider is called. Without those rules a request ending on an `assistant`
turn is a prefill: some models accept it and others refuse it, so re-pointing an alias would turn a
working request into a provider error.

**What changes in the contract.** `role` accepts `assistant`; a list breaking the turn order is
refused with `422 InvalidPayloadError`. Existing callers, which send `user` only, are unaffected.

**Trigger.** The first caller that holds a conversation — an Orchestration Service such as a chat
assistant (§1.3.4).

---

## Deferred decisions

| Stage | The fork |
|---|---|
| 1 | The service's entry in `auth`'s git config: the service's `client_id`, the list of callers with `llm-client` in `allowed_audiences`, and their tokens' TTLs — Stage 11 |
| 3 | The value of `MODEL_TOKENS_PER_SECOND` for each model: taken from a measurement on the target instance rather than from the provider's documentation — fixed at first implementation |
| 6 | The threshold at which the budget check by aggregate stops fitting the time budget and E-5 is switched on — set by measurement rather than in advance |
| 3 | The value of `BUDGET_CAP_DOWNGRADE_PER_CLIENT`: no caller uses the `downgrade` policy yet — fixed together with the first one that does, in the service's settings, which carry placeholders until then |
| 3 | The input's share of the pre-flight time estimate: the term stays out until the prefill speed is measured alongside `MODEL_TOKENS_PER_SECOND`, since a guessed one either refuses requests that fit or does nothing (§3.7.1) |

## Stage 9. Architecture Decision Records

A consolidation of the drafts accumulated over stages 1–8. The identifiers are preserved — the
specification's text references them. The format: Context → Decision → alternatives → Consequences.

**B-1. The prompt arrives from outside; the service has no product domain**
Context: there will be several LLM consumers on the platform, each with its own scenarios.
Decision: the service accepts `system` and `messages` from the caller and stores not a single product
prompt.
Rejected: a registry of named prompts inside `llm-client` (the service starts knowing the products'
scenarios, and changing a prompt's text requires deploying someone else's service); a hybrid of "a
default prompt with an override" (the same coupling, plus it is not obvious whose prompt was applied).
Consequences: the service knows nothing about the products, and a prompt's text changes without
deploying it. In exchange, the quality of an answer stops being its responsibility: a complaint that
"the assistant answers badly" is investigated by the prompt's owner, and the service can show only
numbers.

**B-2. Provider keys are server-side, from Secrets Manager; BYOK is not supported**
Context: the callers here are platform services, not end users.
Decision: each provider's key is kept in SM and is available only to `llm-client`; a caller passes no
key.
Rejected: a BYOK header (there is no subject to bring a key, and passing a secret through the
platform's services end to end widens the surface for a leak); the key in the service's environment
variables (rotation without a deploy becomes impossible).
Consequences: the secret exists in one place, and rotation is replacing a value and restarting one
container. In exchange, this service becomes the only point through which the platform can reach an
LLM at all: its unavailability turns the functionality off for every consumer at once.

**B-3. `llm-client` is a Resource Service, not an Orchestration Service and not a new kind**
Context: the service orchestrates nothing, yet what its "resource" is is not obvious.
Decision: it is classified as a Resource Service; its resources are the registry of providers and
models, the budgets and the usage records; no edit to the framework specification's taxonomy is
required.
Rejected: an Orchestration Service (it calls no other platform service and implements no product
functionality); a new kind in the taxonomy (a term for the sake of one service, when its persistence
and fine-grained authorization are exactly a Resource Service's).
Consequences: the platform's ready-made rules apply to it — authorization, limits, independent
deployment — and the framework specification's taxonomy did not have to be edited. In exchange the
name of the kind is a slight stretch: the "resource" here turns out to be access to someone else's
API rather than data of its own.

**B-4. Budget exhaustion is a manageable policy, not only a refusal**
Context: the budget has to protect the platform's wallet, but a hard refusal is not acceptable in
every scenario — some callers would prefer a cheaper answer to no answer.
Decision: the behaviour on exhaustion of a caller's own budget is set by that caller's `reject |
downgrade` policy; `downgrade` moves the request to a cheaper model set by a **separate setting**,
independent of the logical alias table, and charges it to a **pool of its own** per caller; the actual
model is returned in the response. A provider's exhausted budget is not the caller's to downgrade:
the request moves on to the next candidate, and is refused, whatever the policy, when none is left.
Rejected: `reject` only (it turns the budget into an emergency stop); a silent downgrade without
returning the actual model (the caller cannot tell degradation from normality); downgrading by
re-pointing an alias (it mixes two independent settings — "which model is responsible for what" and
"what to do when the money runs out"); downgrading against the same pool (the ceilings are in tokens
and a cheaper model spends as many, so the repeated check meets the same exhausted counter and the
policy never answers); ceilings in money with a "the call fits the remainder" check (prices would
enter the calculations, and the accepted overspend within a single call would have to go).
Consequences: non-critical scenarios keep working on a cheaper model instead of being refused, and the
caller sees the substitution in the response. In exchange a mode of quiet quality degradation appears:
if nobody watches the share of `downgraded` (§8.4), the platform answers for months with a model other
than the one being asked for.

**B-5. Failover between providers is provided for at design level**
Context: a single provider is a single point of failure for every LLM consumer on the platform.
Decision: having exhausted the retries at the current model, the service switches to the next
candidate of the alias — a chain of **models**, not of providers, because what is called is a model
and no rule derives one vendor's equivalent of another's; the registry states the equivalence. A
candidate that cannot serve the request is passed over rather than refused. Exhausting the candidates
→ `502 UpstreamLlmError`; the actual provider and model are returned in the response.
Rejected: no failover (a provider's failure takes down the platform's whole LLM functionality); the
caller choosing the provider (it returns vendor detail to the contract and makes failover every
service's job).
Consequences: one vendor failing does not take down the platform's LLM functionality, and the switch
is visible in the response. In exchange the chain eats the shared time budget: the less time the first
provider left, the less there is for the second — with a chain longer than two this will have to be
revisited together with the integration ceiling.

**B-7. Synchronous handlers in a threadpool, with no async stack**
Context: the hot path is waiting for a provider's answer, measured in seconds, with almost no CPU
work; meanwhile the platform keeps shared libraries (JWT validation, rate limit, error handling), and
they must not exist in two variants, sync and async.
Decision: the endpoints are synchronous `def` and FastAPI runs them in a threadpool; SQLAlchemy Core
and `psycopg` are synchronous; concurrency is bounded by the thread pool's size, which is enough at a
handful of simultaneous generations.
Rejected: an async stack (async SQLAlchemy, an async `psycopg` pool, async provider clients) — it
forces the platform's shared libraries to be kept in two variants and introduces the "a blocking call
in a coroutine" class of bug, for throughput this iteration does not need. Revisit when the number of
simultaneous generations steadily approaches the thread pool's size.
Consequences: the platform's shared libraries exist in one variant rather than in sync and async
versions. In exchange every generation occupies a thread for the whole wait on the vendor — when the
pool is exhausted requests queue up, and that is the service's only real throughput ceiling.

**B-8. The registry of providers, models and aliases is git config, applied by a rollout**
Context: the set of providers changes rarely and requires review; the alternative is a table in the
database applied hot.
Decision: configuration in the service's git repository, validated at startup, with a change applied
by restarting the container; the file holds only names and references to secrets.
Rejected: the registry in the database (editing vendor configuration without review and without
history, plus divergence between replicas); hot reload of the config (the state "some processes on the
old config" is worse than a short restart, and startup validation stops being a guarantee).
Consequences: a change to vendor configuration goes through review and lands in history, and an
incorrect config fails to bring the service up instead of failing at runtime. In exchange, changing a
model or disabling a provider requires a rollout — reacting to a vendor incident "within a minute" is
not possible.

**B-9. Only the usage log is persistent; the budget is computed from it, and the idempotency keys and the rate limit live in memory**
Context: the service has three kinds of counted state — spend, the daily ceiling, and protection
against duplicates and overload; the question is which of them has to survive a restart.
Decision: the database holds only the append-only usage log; the budget's state is derived from it as
an aggregate over the current window; the idempotency keys and the rate-limit counters live in process
memory.
Rejected: a separate budget counter table — it is a denormalised sum of the usage log, and it gives no
atomic reservation (the check is before the call and the increment after it, so concurrent generations
exceed the ceiling identically in both designs); materialisation is justified by a measurement rather
than in advance (extension E-5). Persistent idempotency keys were rejected separately: they would
protect the case "a restart between attempts", where the first generation was aborted along with the
process and there is nothing to remember, while the real case — "the caller dropped on a timeout, the
service is alive" — is covered by memory. The rule in full: the database holds what is promised to the
outside; memory holds what protects the service.
Consequences: one table instead of three, the budget cannot diverge from the log by definition, and
the lazy window reset does not have to be programmed. In exchange the budget check is two aggregates
per call, which will become noticeable as the log grows (E-5), and the protection against duplicates
holds only within one process.

**B-10. Postgres is a container in the service's compose project**
Context: the framework specification requires a service's dependencies to be containers inside its own
compose project; the alternative is a shared platform instance with a database per service.
Decision: its own Postgres container with a named volume in the `llm-client` compose project.
Rejected: a shared instance (restarting the shared database touches every service, breaking the
independence of a deploy unit); managed RDS on dev (cost and provisioning time for the sake of local
development).
Consequences: the service is deployed and restarted without coordinating with anyone. In exchange the
instance carries as many Postgres containers as there are services, and they share its resources with
no common scheduling.

**B-11. SQLAlchemy Core without an ORM**
Context: the service needs writes to the usage log, aggregates over a window, and migrations; the
domain entities are assembled by repositories by hand and must know nothing about persistence.
Decision: SQLAlchemy Core 2.0 — explicit expressions and one `MetaData` shared with Alembic; no ORM
layer is introduced, and the repositories assemble entities from rows by hand.
Rejected: a declarative ORM — the domain classes would inherit from `Base`, which means `domain/`
would import a persistence library, forbidden by the `import-linter` contract; separate ORM models
mapped into entities — the same manual assembly plus an extra layer. Imperative mapping removes the
dependency problem, but on a domain this size there is nothing for an identity map, change tracking
and cascades to be applied to, while session lifetime and lazy attributes remain; on top of that the
budget is an aggregate over the log (B-9), a query rather than objects to track. Raw SQL in
strings was rejected separately: there is no single `MetaData` for Alembic and no typed support for
expressions. Revisit under the framework specification's S-6.
Consequences: the queries are explicit, one `MetaData` is shared with Alembic, `domain/` is free of
persistence, and the budget aggregate is written as ordinary SQL. In exchange the repositories assemble
entities by hand — as the number of relations grows this will become a noticeable share of the
infrastructure code.

**B-12. A synchronous mode with a pre-flight refusal and an idempotency key; the asynchronous one is an extension**
Context: staying within the synchronous integration ceiling is not guaranteed — a generation's duration
does not follow from the input's size; meanwhile a full two-phase mode would force the service to
store prompts and answers in the database.
Decision: stay synchronous, but add a pre-flight refusal based on a time estimate, an idempotency key
against double payment, and an explicit record of the accounting gap on a timeout; the two-phase mode
is described as extension E-3.
Rejected: an asynchronous mode in this iteration (it breaks the property "the service stores no
content" and requires a queue, a worker, a result TTL and polling by the caller, for load this
iteration does not have); raising the timeouts (the integration ceiling does not move, and the caller
gets a hang instead of an answer); estimating the spend ourselves on a timeout (it spoils the usage
log's trustworthiness for the sake of completeness).
Consequences: the caller gets a refusal in milliseconds instead of a timeout at the thirtieth second,
and a repeat after a dropped connection is not paid for twice. In exchange the service simply does not
serve part of the load, and the spend on aborted calls does not reach the log — the accounting gap is
accepted and measured (§8.4). Only the timeout leaves that gap: a content refusal arrives with figures
the provider confirmed, so it is recorded like any other spend (§7.4).

**B-6. The answer is returned whole; streaming is not supported**
Context: the consumers are services and a CLI, with no interactive token-by-token rendering; the path
outward goes through nginx and the API Gateway.
Decision: the answer is formed in full and returned as one body.
Rejected: SSE or chunked delivery (it complicates the proxy chain, the callers' adapters and `Usage`
accounting, for a UX that machine consumers do not have).
Consequences: the contract stays one response with a complete `usage`, and the proxy chain needs no
special configuration. In exchange an interactive UI on top of the platform is impossible without E-1,
and long answers run into the same time ceiling as everything else.

**B-13. Metrics are structured log events, with no separate metrics system**
Context: the template requires the technical metrics to be fixed, but the framework specification's
topology has neither Prometheus nor a metrics agent — only log collection.
Decision: every generation writes one completion event with a fixed set of fields; the metrics are
derived by aggregating those events on the log-collection side (Stage 11).
Rejected: a `/metrics` endpoint in Prometheus format (it needs a collector and its storage —
components the platform does not have); sending metrics to a cloud service from the code (a network
call in the hot path and a vendor dependency in the application).
Consequences: observability of spend, degradations and failures appears with no new component at all,
and the set of fields is checked by the same allowlist that keeps prompts out of the logs. In exchange
percentiles and sums are computed by a query over the logs, with the delivery delay, and a "the budget
is running out" alert comes out deferred.

**B-14. `system` is a field of the contract, not a message with a role**
Context: providers accept a system instruction differently — as a separate field or as the first
message in the list; meanwhile §3.8 obliges the service not to destroy the role boundary the caller
set.
Decision: `system` is a separate request field; only the `user` role is allowed in `messages` —
`assistant` arrives with a multi-turn conversation (E-6).
Rejected: a single list with a `system` role (the instruction could accidentally be placed after
untrusted data, or lost when concatenating — the boundary that the injection defence depends on
becomes optional); normalising by "the first message is taken to be the system one" (an implicit rule
the caller is obliged to remember); allowing `assistant` without the turn-order rules (a request could
end on an `assistant` turn — a prefill some models refuse — so re-pointing an alias would turn a
working request into a provider error).
Consequences: gluing an instruction together with untrusted content by mistake becomes impossible, and
any provider's adapter receives the boundary explicitly. In exchange the contract diverges slightly
from those vendor APIs where the system role sits in the common list — the adapter is obliged to
perform the conversion.

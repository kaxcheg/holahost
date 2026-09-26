# Holahost — project context

The platform frame specification: `holahost/docs/holahost_frame.md`. A service's spec lives next to the service
itself (`holahost/services/<svc>/docs/`), a tool's — in `holahost/tools/<tool>/docs/`.

## The spec is context, not an argument

The spec is provisional: it records the intent at the time of writing. Citing it ("§7.6 fixes this",
"US-R09 requires it") **does not settle a design dispute**. The first answer to "why this way?" is the substantive
reason: what breaks, for whom and when. The spec is cited as "this is what is written now", not as the reason. No
substantive reason — say so plainly and propose a spec edit.

For a service that has no consumers yet, the cost of changing a public contract is close to zero and grows over
time. This is exactly when "the spec already says so" carries the least weight.

## Code conventions

### Port and repository signatures

One rule for every service of the platform:

- A **query** returns an object, `None` or a list: `get(...) -> Document | None`,
  `top_k(...) -> list[SearchHit]`.
- A **command** returns `None`. A refusal is expressed as a **typed exception** carrying the needed
  context (`RateLimitExceededError` with `retry_after`, `DuplicateRequestError` with the state),
  not as a return value.
- **A boolean result is not used**, in queries or in commands: `False` forces the caller to guess
  what exactly happened — "not found", "not permitted" or "already done".

Consequence: checking existence and ownership is a separate `get` before the command, not a side result of the
command itself. The extra round trip is acceptable: the policy "someone else's is indistinguishable from
nonexistent" stays in one place instead of being spread across return values.

### A port declares its concurrency contract

A port lives in the application layer and describes a **business requirement**, not a storage detail. A
requirement such as "the replacement is atomic" or "a duplicate must not go through twice" belongs to the domain,
so every port method records:

- whether a lock is needed and **on which entity** (a document row, an idempotency key, a counter);
- when the lock may be **skipped** and why — with an explicit reason, not by default;
- whether the implementation must be thread-safe (the process shares a thread pool).

The infrastructure implementation must conform to this contract: the choice of mechanism (`SELECT … FOR
UPDATE`, advisory lock, atomic counter, in-memory CAS) is its own business; whether a lock is taken at all is
not.

### A port declares `raises`

Every port method lists the exceptions it may raise. This is part of the contract:

- the implementation raises nothing beyond what is declared — otherwise the exception surfaces unhandled;
- the caller must **handle** every declared exception or **deliberately let it propagate**, and letting it
  propagate must be visible in the spec or a comment rather than look like an oversight;
- vendor driver errors never reach the application layer — they are translated into the contract's types.

A type is introduced if and only if the caller reacts to it **differently**. By this criterion storage failures
yield three types, not one:

| Type | What it is | Caller's reaction |
|---|---|---|
| `StorageUnavailableError` | connection lost, timeout, DB not responding | retrying within the request is pointless — propagate |
| `ConcurrentUpdateError` | deadlock, serialization failure, lock wait timeout expired | the transaction was rolled back — **retry it** a bounded number of times, then propagate |
| `IntegrityError` | uniqueness, foreign key or `CHECK` violation | a defect: invariants or locking should have prevented it earlier. Do not retry — propagate |

If a key conflict is a normal scenario (redelivery, idempotent insert), it is resolved by the **implementation**
(`ON CONFLICT`), not by exception handling in the caller.

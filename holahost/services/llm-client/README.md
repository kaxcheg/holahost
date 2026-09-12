# llm-client

> **Design only.** This directory holds no implementation — the service is specified but not built.
> What follows describes the intended contract, so that services designed against it stay honest.

A Resource Service that is the platform's single point of contact with external LLM providers.
Without it every service repeats the same four things: a provider SDK, a provider key, a retry
policy for `429` and overload, and its own accounting. Platform-wide spend is then visible nowhere,
and changing the model means editing N services.

See the platform contract in [`../../README.md`](../../README.md).

## What it takes off a caller

- One operation, `generate`, instead of a provider's SDK and HTTP contract.
- **Logical model aliases** (`fast` / `quality` / `default`) resolved in config, so swapping the
  platform's model is a change to one service's configuration rather than to every caller.
- **Centralised retries** with backoff on upstream `429`, overload and 5xx.
- **Failover** to the next provider in a chain when retries are exhausted, so one provider going
  down does not take every LLM consumer with it.
- **Budgets with an active policy** — `reject`, or `downgrade` to a cheaper model where a cheaper
  answer is acceptable.
- A usage log broken down by caller, provider and model.
- One error taxonomy at the edge, instead of vendor error codes.
- Provider keys held by this service alone: one secret, rotated in one place.

The service has no product domain. The prompt always arrives from outside; scenarios live with the
caller.

## Intended API

Base path `/api/llm-client`.

```
POST /generate                     Idempotency-Key: <optional>

{ "model": "fast", "system": "You are …",
  "messages": [{ "role": "user", "content": "…" }],
  "max_tokens": 800, "temperature": 0.3 }

200 { "text": "…",
      "usage": { "input_tokens": 1240, "output_tokens": 310 },
      "provider": "anthropic", "model": "claude-haiku-4-5",
      "finish_reason": "stop", "downgraded": true, "failed_over": false }
```

`system` is its own field rather than a message with a `system` role: the role boundary the caller
set has to survive the service, and a separate field makes it impossible to accidentally splice an
instruction together with untrusted data.

`provider` and `model` in the response are the **actual** ones. When they differ from what was
asked, `downgraded` says a budget policy fired and `failed_over` says a provider switch did. A
caller that cares which model answered must read the response, not assume the request.

## Domain

`Provider` (the registry), `Model` (context and output ceilings, price per million tokens),
`Budget` (a spend ceiling over a window plus the policy when it is exhausted), `Usage` (the record
of one call).

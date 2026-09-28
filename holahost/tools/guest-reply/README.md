# guest-reply

A console tool that answers a guest's question from a property's own document, by calling
`rag-documents` for the relevant fragments and `llm-client` for the reply. It is not a deploy unit:
no image, no ECR, no environment beyond a developer's machine.

Its point is to be the thinnest possible real caller of the platform. Running it end to end against
a local stack exercises the whole contract — the `backbone` network, offline JWT validation,
layered rate limiting, the error envelope, `X-Request-ID` propagation — without a frontend or a
second deploy unit. It does what an Orchestration Service will later do, and no more: it holds no
domain logic of its own, and anything it grows beyond calling services in order, reacting to their
error codes and printing is a sign the decision belongs in a service instead. The one piece of
product logic, the "answer the guest" prompt, is data: the assets in `guest_reply/prompt/`.

See the platform contract in [`../../README.md`](../../README.md); the full design is
[`docs/guest_reply_spec.md`](docs/guest_reply_spec.md).

## Commands

```
guest-reply ingest  <file> [--name <str>] [--json]
guest-reply replace <document_id> <file> [--name <str>] [--json]
guest-reply ask     <document_id> "<guest_message>" [--json]
guest-reply ask     --file <file> "<guest_message>" [--json]     # one-shot, no stored document
guest-reply rm      <document_id> [--json]
```

stdout carries only the result — a `document_id`, an answer's text — and `--json` turns it into
exactly one JSON object, which always carries the run's `request_id`: the key that finds the run in
both services' logs. Diagnostics go to stderr.

## Configuration

| Variable | Required | What |
|---|---|---|
| `HOLAHOST_RAG_DOCUMENTS_URL` | yes | `rag-documents`' origin, e.g. `http://localhost:8080` |
| `HOLAHOST_LLM_CLIENT_URL` | yes | `llm-client`'s origin, e.g. `http://localhost:8081` |
| `HOLAHOST_TOKEN` | yes | a token from the [dev minter](../dev-minter/README.md), until `auth` exists |
| `HOLAHOST_MODEL_ALIAS` | no | the `llm-client` alias to generate with; `default` if unset |

Two origins rather than one: dev has no gateway, so each service answers on its own published port;
the client adds each service's `/api/<svc>` path. Plain `http` is accepted only for a local host.
A missing or invalid variable is refused before any network call, and no value — the token least of
all — is ever printed.

## Running it locally

```bash
poetry install
make -C ../dev-minter dev-up                                  # the minter, on backbone
(cd ../../services/rag-documents && make dev-up)              # :8080
(cd ../../services/llm-client && make dev-up)                 # :8081
export HOLAHOST_RAG_DOCUMENTS_URL=http://localhost:8080 HOLAHOST_LLM_CLIENT_URL=http://localhost:8081
export HOLAHOST_TOKEN=$(make -s -C ../dev-minter token)       # valid 15 minutes
poetry run guest-reply ask --file guidebook.pdf "What time is check-in?"
```

## Exit codes

| Code | Situation |
|---|---|
| `0` | success |
| `1` | configuration error — a variable is unset or invalid |
| `2` | usage error — unknown command, missing argument, `--file` together with a `document_id` |
| `3` | the file does not exist or cannot be read |
| `4` | document not found |
| `5` | no relevant context — the search came back empty and generation was never called |
| `6` | refused by a limit — a rate limit not worth waiting out, or the token budget |
| `7` | the LLM provider is unavailable |
| `8` | a service was unreachable, timed out, or could not validate tokens (`503`) |
| `9` | a service answered outside its contract |
| `10` | the token was refused (`401`) — mint a new one |
| `11` | a service refused the request itself — the file, the message, the model alias |

Code `5` is deliberately distinct from `0`: "no answer, because the document has nothing to say" is
not success, and a script calling the tool has to tell them apart without parsing prose. An error
prints the service's own `code`, its message and its `details`; with `--json` the error object
carries them as they came.

A `429` from the rate limiter is waited out when `Retry-After` is at most a minute, up to three
times; a longer wait, or a spent budget, is reported at once with how long to wait. Nothing else is
retried: the services retry upstream themselves.

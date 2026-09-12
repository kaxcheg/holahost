# guest-reply

> **Design only.** This directory holds no implementation — the tool is specified but not built.

A console tool that answers a guest's question from a property's own document, by calling
`rag-documents` for the relevant fragments and `llm-client` for the reply. It is not a deploy unit:
no image, no ECR, no environment beyond a developer's machine.

Its point is to be the thinnest possible real caller of the platform. Running it end to end against
a local stack exercises the whole contract — the `backbone` network, offline JWT validation,
layered rate limiting, the error envelope, `X-Request-ID` propagation — without a frontend or a
second deploy unit. It does what an Orchestration Service will later do, and no more: it holds no
domain logic of its own, and anything it grows beyond the list below is a sign the decision belongs
in a service instead.

See the platform contract in [`../../README.md`](../../README.md).

## Commands

```
guest-reply ingest  <file> [--name <str>] [--json]
guest-reply replace <document_id> <file> [--name <str>] [--json]
guest-reply ask     <document_id> "<guest_message>" [--json]
guest-reply ask     --file <file> "<guest_message>" [--json]     # one-shot, no stored document
guest-reply rm      <document_id> [--json]
```

`--json` switches to machine-readable output. Configuration comes from `HOLAHOST_API_BASE` plus
credentials; a missing required variable is a configuration error raised before any network call,
and no credential value is ever printed, including in error messages.

## Exit codes

| Code | Situation |
|---|---|
| `0` | success |
| `1` | usage error — unknown command, missing argument, mutually exclusive flags |
| `2` | configuration error — a required environment variable is unset |
| `3` | the file does not exist or cannot be read |
| `4` | document not found |
| `5` | no relevant context — the search came back empty and generation was never called |
| `6` | rate limited — `Retry-After` was honoured the maximum number of times without success |
| `7` | the LLM provider is unavailable |
| `8` | a service was unreachable or timed out |
| `9` | a service returned an error the tool does not interpret |

Code `5` is deliberately distinct from `0`: "no answer, because the document has nothing to say" is
not success, and a script calling the tool has to tell them apart without parsing prose.

# rag-documents

A Resource Service that turns an uploaded document into searchable fragments and answers similarity
queries over them. It is the retrieval half of any Holahost feature that has to ground an answer in
a specific property's own material — a house manual, a guidebook, a set of rules — rather than in a
model's general knowledge.

Upload a PDF, DOCX, Markdown or plain-text file; the service parses it, splits it into overlapping
token windows, embeds each window locally and stores the vectors in Postgres. A search embeds the
query and returns the closest fragments of one document, with the page they came from.

See the platform contract in [`../../README.md`](../../README.md).

## API

Base path `/api/rag-documents`. Every route but health requires `Authorization: Bearer <jwt>`.
The full contract is [`docs/openapi.json`](docs/openapi.json).

| Method and path | Purpose | Success |
|---|---|---|
| `POST /documents` | create a document (`multipart/form-data`: `file`, `name`) | `201` |
| `PUT /documents/{id}` | replace its content, keeping the id | `200` |
| `POST /documents/{id}/search` | find fragments | `200` |
| `GET /documents/{id}` | metadata | `200` |
| `DELETE /documents/{id}` | delete it and its fragments | `204` |
| `GET /health` | readiness — database reachable and model loaded | `200` / `503` |

Search is a `POST`: the query runs to thousands of characters and has no business appearing in a URL
or in a proxy log. Replace is a `PUT` on an existing id, so consumers' references never go stale.

## Domain

**`Document`** — `id`, `owner`, `name`, `mime_type`, `chunk_count`, `created_at`, `updated_at`. The
owner is the `sub` of the token that created it and never changes. A document with zero chunks is
not a state the service can be in: an empty parse is rejected rather than stored.

**`Chunk`** — `id`, `document_id`, `index`, `text`, `embedding`, `page`. Subordinate to the document
aggregate: it has no repository of its own, is immutable, and is born and destroyed only with its
document. A chunk never crosses a page boundary, so its provenance is unambiguous.

The source file itself is not kept. It lives for the duration of the request and is discarded — this
service is an index, not a file store.

## Parameters

| Parameter | Value | Why |
|---|---|---|
| `ALLOWED_MIME_TYPES` | PDF, DOCX, Markdown, plain text | the formats a parser exists for; no OCR |
| `MAX_UPLOAD_SIZE` | 8 MiB | below the gateway's payload ceiling |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | multilingual, 384 dimensions, runs on CPU |
| `CHUNK_WINDOW_TOKENS` / overlap | 120 / 16 | the window must stay under the model's 128-token input, or the embedder silently truncates |
| `MAX_CHUNKS_PER_DOCUMENT` | 500 | caps both ingest time and per-document search cost |
| `SEARCH_TOP_K` | 5 | as many fragments as fit a caller's prompt without crowding out the instruction |
| `SIMILARITY_THRESHOLD` | 0.30 | a starting value, meant to be calibrated on real documents |
| `INGESTION_P95_BUDGET` | 20 s | headroom under the gateway's 30-second synchronous ceiling |
| Rate limits | 60/h ingest, 600/h read | ingest costs two orders of magnitude more than a search |

## Design decisions

- **Ingest is synchronous.** Parsing, chunking, embedding and the write all happen inside one HTTP
  request, and the caller gets a document that is already searchable. There is no queue in the
  platform's topology to make it otherwise — the cost is that file size is bounded by a time budget.
- **Vectors live in Postgres via `pgvector`**, and similarity is computed by the database. Embeddings
  never travel into the application or occupy process memory.
- **No ANN index.** A search is always scoped to one document, so a btree on `chunks(document_id)`
  narrows the set to at most a few hundred rows and exact cosine distance is both faster and exactly
  recallable. An approximate index earns its keep only with multi-document search.
- **Embeddings are computed in-process**, not through `llm-client`: the model is local, so routing it
  through a service facade would add a network hop per chunk and buy nothing.
- **Owner isolation is enforced by row-level security**, not by repository filters — and the
  application refuses to start if it ever connects as a role that can bypass RLS.
- **Another owner's document answers `404`, never `403`.** A `403` confirms that an id exists, which
  turns id enumeration into reconnaissance.
- **Replace is one atomic operation.** Assembled by the caller from delete + create it would leave a
  window with no document, lose data if the second call failed, and change the id.

## Running it locally

```bash
make dev-up      # build, migrate, start the app and its Postgres
make dev-logs
make dev-down-v  # stop and wipe volumes
```

Configuration comes from `infra/envs/dev/.env`, a local copy of the committed `.env.example`.
Operating it on staging and prod — first deploy, verification, upgrade, rollback, secret rotation —
is [`docs/runbook.md`](docs/runbook.md). The design in full — the domain, the schema, the error
contract and the decisions behind them — is
[`docs/rag_documents_spec.md`](docs/rag_documents_spec.md).

```bash
make test        # unit tests
make test-int    # integration tests (needs Docker)
make ci-local    # what CI runs: hooks, the full suite, the OpenAPI contract check
```

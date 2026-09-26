---
name: build-start
description: Entry point of a build session — loads the spec sections and the ticket state, then hands over to build-session (Path A new ticket, Path B continue).
argument-hint: "[ticket-id ...] [layer] [spec path]"
---

# Build Start

Entry point for build sessions. Loads context, then routes to Path A or B per `build-session` skill.

## Step 0 — Session directory

A build session runs from the service it builds: `.build-state/` and the spec are resolved from the session's
directory. If the session's primary working directory is not `holahost/services/<svc>` of this repository — exactly
that directory, not the repository root and not a subdirectory such as `backend/` — warn the user before anything
else: "This session runs in `<dir>`; build for a service runs from `holahost/services/<svc>`, where its
`.build-state/` and spec live." Continue only if the user confirms.

## Step 1 — Route (computed — do not re-derive it)

```!
python3 .claude/bin/procs build route --project "${CLAUDE_PROJECT_DIR}" <<'__PROCS_ARGS__'
$ARGUMENTS
__PROCS_ARGS__
```

- `ROUTE: STOP` → give the user the MESSAGE and stop.
- `ROUTE: ASK` → ask the user what the MESSAGE names, then re-run `/build-start` with the answer. A new ticket
  (Path A) needs ticket ID(s) and a layer before anything is loaded.
- `ROUTE: PATH_A` / `ROUTE: PATH_B` → continue. Each `NOTE:` line is an open point to settle with the user first.

Forms: `/build-start T-05 domain` · `/build-start T-05 T-06 T-07 domain` · `/build-start T-05 domain docs/my_spec.md`.
Arguments: ticket ID(s), then `<layer>` ∈ `domain | application | infrastructure | interface | frontend | infra | ci-cd`,
optionally a spec path — the token containing a `/` or ending in `.md`; it overrides auto-location under `./docs/`.
**Multiple ticket IDs** are concatenated with `-` into a single combined ID used for all state files and
commands: `B-06 B-07 domain` → `<TICKET-ID>` = `B-06-B-07`, layer = `domain`. Without ticket tokens the single
`in_progress` ticket is continued (Path B, layer from session.md).

The backend layers (`domain | application | infrastructure | interface`) are the Clean Architecture decomposition —
use them only when the spec's Tech Constraints chose Clean Architecture; otherwise treat the whole backend as
`application` (re-run `/build-start <ids> application` to get its sections). `frontend | infra | ci-cd` map to the
remaining Backlog groups.

## Step 2 — Load context

Load every range under SECTIONS TO READ **in full** — do not summarize, skip, or defer.

- `UNMATCHED` — no heading carries the stage's keywords: match the stage to a heading of the HEADINGS list by
  meaning (case-insensitive; ignore numeric prefixes and `-`/`_`/space separators), tolerant of analogous wording,
  and read it by its line-range. Sections absent from the spec are skipped (a small/abstract project may omit
  Frontend, Detailed Flow, etc.). Conceptual (6) is never loaded — it is the un-signatured draft of **Detailed
  Sequence Flow (9)**.
- `AMBIGUOUS` — several headings fit one stage: decide by their content; still unclear → ask the user.
- **Backlog (14)** — read the entry for each individual ticket ID (one line per ticket: `[ID] [Name] — [scope]`),
  printed under BACKLOG ENTRIES. **Multi-ticket verification:** confirm every individual ID sits under the
  `<layer>` group. If any ID belongs to a different layer, stop: "Ticket `<ID>` is in layer `<actual>`, not
  `<layer>`. Re-run with matching IDs."
- **Loading User Stories (3):** if the backlog entry names a US-ID, load that story (description + **all AC
  items**) in full — its range is listed as `story <US-ID>`. If it does not (`STORIES BY SCOPE`), identify the
  relevant story/stories in section 3 by matching the ticket's name/scope, and load them with all AC. `infra` /
  `ci-cd` tickets are technical — their requirements come from Infrastructure (12) / CI/CD (13) / Tech
  Constraints (2), not from user stories.
- **Path B only:** also read the TICKET FILES marked `exists`.

## Step 3 — Execute

With context loaded, follow the `build-session` skill starting at Path A or Path B.

The loaded spec is **provisional, not final** — it is refined as development progresses. Principal decisions left
unsettled by it are clarified with the user and recorded in `clarifications.md` (see build-session `## Source data`).

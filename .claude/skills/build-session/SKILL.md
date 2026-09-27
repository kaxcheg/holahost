---
name: build-session
description: >
  The build protocol for one or several tickets, start to finish: admits the ticket, loads its spec sections, then
  exploration, design, plan, implementation, validation.
argument-hint: "<ticket-id ...> [layer] [spec path]"
disable-model-invocation: true
---

**RIGID skill — follow every step exactly, in order. No skipping, no adapting.**

Steps marked **⏹** are checkpoints: a checkpoint is finished only when its line in the
**Protocol ledger** of `session.md` is ticked with the evidence noted (see `## Ticket state`).
An unticked checkpoint blocks the step after it.

## Language

Comments, docstrings, documentation and every VCS-facing artifact (commit subject and body, PR
title and body, branch names/slugs) are **in English**, regardless of the dialogue language.
Session dialogue, clarifying questions and `.build-state/` files follow the user's language.

Code style, naming and toolchain conventions are owned by `./CONTRIBUTING.md` (Code Style) and
the spec's Tech Constraints — this skill does not restate them.

## Source data

Source Data (the spec located at Start) is **read-only** and **provisional, not final**:
context, never the argument. "The spec says so" settles nothing — give the substantive reason
(what breaks, for whom, when) or say plainly there is none and propose the spec change. Draft
code snippets in it are intent to reason through, never to copy: validate against the codebase
and current library APIs (`## Context7`).

**Principal vs routine.** A decision is *principal* when it touches architecture, public
contracts/API, data schema, scope, or diverges from the spec's stated intent. Principal decisions
left unsettled by the spec are **clarified with the user, never resolved silently**. Routine ones
(naming, internal structure, code organization) are resolved against existing codebase patterns
without asking; where codebase and Source Data disagree on a routine matter, the codebase is the
source of truth.

**`clarifications.md`** takes exactly one kind of entry: a *principal* Source Data discrepancy or
decision that surfaced while doing this ticket's work, not yet fixed in Source Data, and a
candidate to fold back into it at the **Fold-back** step. Test before writing: *did this surface
while doing the work, and would it plausibly become a Source Data edit?* If either answer is no,
it is session dialogue, not an entry. Not entries: routine implementation questions, local
naming/structure choices, plan-review nits that don't touch Source Data, process picks (e.g. the
testing approach) unless they diverge from something Source Data states. Append only, never
delete; keep in context for the entire session. In the protocol, "→ clarifications.md" means:
apply this rule.

## Models

The main loop — this skill and `/build-commit` — runs on the session model (`"model"` in `.claude/settings.json`).
Subagents run on the model of their row, edited by hand for the task at hand; every dispatch passes it as `model`,
and the `agent-model` guard blocks one that differs from its row or whose type has no row.

| agent | model |
|---|---|
| `test-runner` | `sonnet` |
| `feature-dev:code-explorer` | `sonnet` |
| `feature-dev:code-architect` | `fable` |
| `general-purpose` — runs `code-review` | `fable` |

`code-review` is a built-in skill, not an agent: it runs on the model of whoever invokes it. To run it on its row's
model, dispatch a `general-purpose` subagent whose whole task is to invoke the `code-review` skill with the given
args (scope, specs, effort level), fix nothing, and return every finding verbatim — file, line, summary, failure
scenario. Present that report to the user unchanged.

## Subagents

Bulk, mechanical work — codebase exploration, test runs, architecture fan-out — is delegated to
`feature-dev:code-explorer`, `feature-dev:code-architect` and `test-runner`, never done inline
in the main loop. Inline is a last resort only when the agent fails for environment reasons, and
then say so explicitly.

Every explorer/architect prompt states that the Source Data is already loaded in the parent
context and must not be re-read, and scopes the agent to **codebase files only** (source, tests,
config).

## Context7

For every framework/library the work touches — including the language itself for language-level
features — run `resolve-library-id`, then `query-docs` for the specific area. Cover every library
in the spec's Tech Constraints stack (language, frameworks, ORM/DB driver, test framework, SDKs,
…), well-known ones included: training-data contracts, signatures and configuration may be
outdated. Never rely on training-data API assumptions. The protocol marks the three checkpoints
where this is due: before proposing a design, before writing code into the plan, before
implementing an external-library API call.

## Session Protocol

A ticket runs start to finish in one session: nothing restores it in a new context. Compaction keeps the session
but not its detail, so it follows `### Compaction`.

### Compaction

On a manual `/compact`, or when the `context-watch` hook says auto-compaction is near, offer it at the next clean
point: a checkpoint or a plan task just finished, nothing half-edited, no agent running.

Before — the user runs `/compact` only after both:
1. The ledger is ticked with evidence, the finished `plan.md` steps are `[x]`, and every principal decision of the
   dialogue is in `clarifications.md`.
2. `session.md` has a `## Resume` section, rewritten each time: the protocol step and plan task, the branch and what
   is uncommitted, the route's `SECTIONS TO READ` ranges, and whatever the next step needs that no file holds.

After, before anything else:
1. Re-read this `SKILL.md` in full, then `session.md`, `clarifications.md`, `plan.md`, and the spec ranges from
   `## Resume` in full.
2. Check the branch and `git status` against `## Resume`, tell the user the step you resume at, then continue.

### Start

The route (computed — do not re-derive it):

```!
python3 .claude/bin/procs build route --project "${CLAUDE_PROJECT_DIR}" <<'__PROCS_ARGS__'
$ARGUMENTS
__PROCS_ARGS__
```

- `ROUTE: STOP` → give the user the MESSAGE and stop.
- `ROUTE: ASK` → ask the user what the MESSAGE names, then re-run `/build-session` with the answer.
- `ROUTE: START` → load every range under SECTIONS TO READ **in full** — do not summarize, skip, or defer:
  - `UNMATCHED` — no heading carries the stage's keywords: match the stage to a heading of the HEADINGS list by
    meaning (case-insensitive; ignore numeric prefixes and `-`/`_`/space separators), tolerant of analogous
    wording, and read it by its line-range. Sections absent from the spec are skipped (a small/abstract project may
    omit Frontend, Detailed Flow, etc.). Conceptual (6) is never loaded — it is the un-signatured draft of
    **Detailed Sequence Flow (9)**.
  - `AMBIGUOUS` — several headings fit one stage: decide by their content; still unclear → ask the user.
  - **Backlog (14)** — the entry of each ticket ID is printed under BACKLOG ENTRIES. Confirm every ID sits under
    the `<layer>` group; one that does not → stop: "Ticket `<ID>` is in layer `<actual>`, not `<layer>`. Re-run
    with matching IDs."
  - **User Stories (3)** — a story the backlog entry names (`story <US-ID>`) is loaded in full with **all AC
    items**; for `STORIES BY SCOPE`, find the stories in section 3 by the ticket's name/scope and load them with
    all AC. `infra` / `ci-cd` tickets are technical — their requirements come from Infrastructure (12) / CI/CD
    (13) / Tech Constraints (2), not from user stories.

Forms: `/build-session T-05 domain` · `/build-session T-05 T-06 T-07 domain` · `/build-session T-05-07 domain` ·
`/build-session T-05` · `/build-session T-05 domain docs/my_spec.md`. Arguments: ticket ID(s), then optionally
`<layer>` ∈ `domain | application | infrastructure | interface | frontend | infra | ci-cd`, optionally a spec path —
the token containing a `/` or ending in `.md`; without it the spec is the one whose Backlog lists the ticket. Without
a layer it is the one the Backlog group of the tickets names; a group that names none, or could be two (a bare
`Infrastructure`), routes to ASK. **Multiple
ticket IDs** are concatenated with `-` into a single combined ID used for all state files and commands:
`B-06 B-07 domain` → `<TICKET-ID>` = `B-06-B-07`. **A range** is an ID followed by a bare last number: `T-05-07`
stands for `T-05` through `T-07` and is itself the `<TICKET-ID>`. The backend layers (`domain |
application | infrastructure | interface`) are the Clean Architecture decomposition — use them only when the spec's
Tech Constraints chose Clean Architecture; otherwise treat the whole backend as `application`. `frontend | infra |
ci-cd` map to the remaining Backlog groups.

### Setup

1. **The state files** — run `python3 .claude/bin/procs build scaffold <STATE>` with the route's `STATE`: it
   creates `<STATE>/session.md` and `clarifications.md` from the templates (`## Ticket state`) with status
   `in_progress`, and never overwrites an existing file.

2. ⏹ **Spec review** — run `code-review` (the `general-purpose` dispatch of `## Models`) at effort `high` with the
   spec as a path target, scoped to the ranges loaded at Start: contradictions, gaps and ambiguities that would
   mislead this ticket's work. Present the findings unchanged → clarifications.md.

3. **Explore** — launch 2–3 `feature-dev:code-explorer` agents in parallel (`## Subagents`), each on a different
   aspect: entry points and direct dependencies of the ticket;
   similar features/patterns and how they are implemented; test coverage and test patterns of
   the affected modules. Read every key file they identify before the design dialogue.

4. **Design exploration** — collaborative dialogue turning the ticket into an approved design.
   No code, no implementation skill, no plan writing until the user approves the design.
   - Clarify one question at a time: purpose, constraints, success criteria; multiple-choice when
     possible. Discrepancies and principal decisions as they arise → clarifications.md.
   - ⏹ **Context7 — design**: every framework/library the design will touch, before proposing
     approaches.
   - Propose 2–3 approaches with trade-offs, recommended option first. For a broad design space
     dispatch 3 parallel `feature-dev:code-architect` agents: minimal changes
     (smallest footprint, maximum reuse) / clean architecture (maintainability, abstractions) /
     pragmatic balance (speed + quality, fits team context).
   - Present the design in sections scaled to complexity (architecture, components, data flow,
     error handling, testing); get approval section by section.
   - Self-review before locking: placeholders (TBD/TODO/vague), internal consistency, scope
     (one plan or decomposition), ambiguity (two readings → pick one explicitly). Fix inline, no
     re-review.

5. **Branch** — suggest a name per Branch Naming in `./CONTRIBUTING.md`, get approval, create it.

6. ⏹ **Testing approach** — assess the ticket, recommend with justification. The choice is
   captured by the plan's task variant; → clarifications.md only if it diverges from an approach
   Source Data explicitly mandates.
   - **TDD** — domain logic, value objects, use cases, parsers, formatters: units with clear
     inputs/outputs exercisable with mocks/fakes.
   - **Code-first** — infrastructure adapters needing real external services, IaC/deploy tickets,
     CLI DI wiring, exploratory/tuning tasks: the feedback loop is integration tests; TDD is
     circular or meaningless here.
   - **Mixed** — TDD for the unit-testable parts, code-first for the rest.

7. **Plan** — write `<STATE>/plan.md` per `plan.template.md` (header, task
   structure in the chosen testing variant, granularity and no-placeholder rules).
   - Scope check first: multiple independent subsystems → suggest one plan per subsystem, each
     producing working, testable software on its own.
   - Map the file structure before defining tasks: which files to create or modify, one
     responsibility each, following established codebase patterns.
   - ⏹ **Context7 — plan**: every library whose code appears in the plan.
   - Self-review before presenting: spec coverage (a task for every requirement of the approved
     design), placeholders, type and method-name consistency across tasks. Fix inline.

8. Review the plan with the user → clarifications.md.

### Work

1. Review the plan critically before starting — raise concerns with the user before touching
   code.
2. Conventions and naming: Code Style in `./CONTRIBUTING.md`.
3. Per task: follow each step exactly → run the verifications as specified → mark `[x]`.
4. During implementation:
   - **Stop and ask** on a blocker (missing dependency, failing test, unclear instruction),
     critical plan gaps, repeatedly failing verification, or when what you find contradicts what
     the spec assumed — a step built on a stale assumption is a discrepancy to clarify, not to
     force through. Do not guess. → clarifications.md.
   - ⏹ **Context7 — implementation**: before implementing any external-library API call.
   - Plan updated on feedback → re-review before continuing.
   - Intermediate validation: the project's test and static-type commands from the spec's Tech
     Constraints / CI/CD sections; the formatter/linter may run via a PostToolUse hook or
     pre-commit.
   - Re-run `feature-dev:code-explorer` when the codebase changed and dependencies
     need re-checking.
5. **User review** — present the completed work → clarifications.md; proceed on approval.
6. ⏹ **Prose pass** — strip the record of how the work happened. Comments, docstrings, specs and
   READMEs state what is true now; how it got that way belongs to git history and to
   `clarifications.md`. Over the whole diff:
   - cut review archaeology ("found for real, not guessed", "originally lived in X", "used to be
     Y", "regression from", "prior rounds", "omission: decided in §N but never drafted") — keep
     the fact it protected, drop the story;
   - cut restatement — one owner per fact, a reference from the others;
   - remove every reference to `.build-state/`, `session.md`, `clarifications.md` — they do not
     exist for a reader of the repository;
   - keep the trap a comment prevents, the rejected alternative and why, the reason a
     non-obvious line is there.
7. ⏹ **Fold-back** — propose every `clarifications.md` entry for inclusion in Source Data; add or
   update only the provisions the user agrees to (Source Data is never modified without that).
   These edits land in the same commit/PR as the code.
8. `/build-commit` — tests, code-review, local checks, commit, push, PR, CI, squash merge; models
   per `## Models`.
9. `session.md`: status `completed`. Optionally `/revise-claude-md` when the ticket surfaced
   non-obvious project learnings; skip if routine.

## Ticket state — `<STATE>/`

`<STATE>` is `.build-state/<TICKET-ID>/` in the directory that holds the spec's `docs/` — for a service,
`holahost/services/<svc>/.build-state/<TICKET-ID>/`. The route prints it as `STATE`.

| file | content | origin |
|---|---|---|
| `session.md` | status and the **protocol ledger** — what the guards read | `session.template.md`, Setup step 1 |
| `clarifications.md` | principal Source Data discrepancies pending fold-back (`## Source data`) | `clarifications.template.md`, Setup step 1 |
| `plan.md` | implementation plan | Plan step, per `plan.template.md` |
| `context7.log` | every `query-docs` lookup made for the ticket — evidence for the Context7 gate | PostToolUse hook, automatic; never edited by hand |
| `context-watch` | the session already told that auto-compaction is near | `context-watch` hook, automatic |

Templates live next to this `SKILL.md`, in `.claude/skills/build-session/`, not the project root; the scaffold
command (Setup step 1) copies them with `TICKET-ID` substituted. Completed tickets stay in
place with status `completed`.

**Protocol ledger.** `session.md` carries one checkbox per ⏹ checkpoint and per user approval
(design, plan). Tick it the moment the checkpoint is done, with the evidence (e.g.
`context7: design — fastapi, sqlalchemy`).

**Guards** (wired by the `hooks` of the project's `.claude/settings.json`; code in `.claude/lib/procs/build/guards.py`;
the permission allowlist is the same `.claude/settings.json`) enforce
the checkpoints mechanically while a ticket is `in_progress`: every turn re-injects the open ledger lines; an Agent
dispatch without an allowed `model` is blocked; writing `plan.md` or any project file is blocked until a Context7
lookup is recorded in `context7.log` — `plan.md` also until "design approved" is ticked, project files until "plan
approved" is; `git commit` on the default branch is blocked. A blocked call is a checkpoint you
skipped — do the step, then retry; never route around the guard.

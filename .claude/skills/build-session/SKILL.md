---
name: build-session
description: >
  Use for any ticket work during the Build phase, once `/build-start` has loaded the spec
  and the ticket: exploration, design, plan, implementation, validation, session state.
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

Source Data (the spec `/build-start` located) is **read-only** and **provisional, not final**:
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

Two named settings. Every Agent-tool dispatch passes one of them as the explicit `model`
parameter — never omit it: an omitted model inherits the main-loop model, which wastes cost and,
on the 1M-context variant, trips a credit gate that fails the subagent outright.

| setting | value | dispatched with it |
|---|---|---|
| `low_model` | `sonnet` | `test-runner`, `feature-dev:code-explorer` |
| `high_model` | `fable` | `feature-dev:code-architect`, `code-review` (inside a `general-purpose` subagent) |

`code-review` is a built-in skill, not an agent: it runs on the model of whoever invokes it. To
run it on `high_model` regardless of the session model, dispatch a `general-purpose` subagent
with `model: high_model` whose whole task is to invoke the `code-review` skill with the given
args (scope, specs, effort level), fix nothing, and return every finding verbatim — file, line,
summary, failure scenario. The main loop presents that report to the user unchanged. Such a
subagent has the `Skill` tool with `code-review` available but no findings UI, so its text report
is the deliverable.

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

### Path A: New Ticket

**Read `steps/path-a.md` (next to this file) before step 1, and again in every fresh context (`/compact`, `/clear`,
`/new`, a new launch) while Path A is unfinished** — it holds the full text of every step. The order and the checkpoints:

1. Source Data and ticket loaded by `/build-start`.
2. Create `session.md` and `clarifications.md` from the templates (the scaffold command of `steps/path-a.md`); status `in_progress`.
3. **Explore** — 2–3 parallel `feature-dev:code-explorer` agents (`low_model`); read every key file they identify.
4. **Design exploration** — no code, no implementation skill, no plan writing until the user approves the design.
   ⏹ **Context7 — design**. Do **not** write `design.md` yet.
5. **Branch** — name per Branch Naming in `./CONTRIBUTING.md`, approval, create.
6. ⏹ **Testing approach** — TDD / code-first / mixed.
7. **Plan** — `.build-state/<TICKET-ID>/plan.md` per `plan.template.md`. ⏹ **Context7 — plan**.
8. Review the plan with the user → clarifications.md.
9. **Save the design** to `.build-state/<TICKET-ID>/design.md`. Update `session.md`: artifacts, progress, ledger.

### Path B: Continue Ticket (after `/new`, `/clear`, `/compact`, or a new launch)

1. `/build-start` loaded Source Data and the ticket files.
2. Report the restored context — ticket, branch, progress (task/step from `plan.md`), ledger
   state, clarifications and design loaded — and continue from where work stopped.

### Work (both paths)

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
   - Re-run `feature-dev:code-explorer` (`low_model`) when the codebase changed and dependencies
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

## Ticket state — `.build-state/<TICKET-ID>/`

| file | content | origin |
|---|---|---|
| `session.md` | development state: metadata, task context, progress, files, **protocol ledger** | `session.template.md`, at ticket creation |
| `clarifications.md` | principal Source Data discrepancies pending fold-back (`## Source data`) | `clarifications.template.md`, at ticket creation |
| `plan.md` | implementation plan | Plan step, per `plan.template.md` |
| `design.md` | approved design | saved after plan approval |
| `context7.log` | every `query-docs` lookup made for the ticket — evidence for the Context7 gate | PostToolUse hook, automatic; never edited by hand |

Templates live next to this `SKILL.md`, in `.claude/skills/build-session/`, not the project root; the scaffold
command (Path A step 2) copies them with `TICKET-ID` substituted. Completed tickets stay in
place with status `completed`. Every `/clear`, `/compact` or new launch is a fresh context:
`/build-start` restores it from these files, the only bridge between sessions; switching tickets
is `/build-start <ticket-id>`.

**Protocol ledger.** `session.md` carries one checkbox per ⏹ checkpoint and per user approval
(design, plan). Tick it the moment the checkpoint is done, with the evidence (e.g.
`context7: design — fastapi, sqlalchemy`). Path B reports the ledger before continuing.

**Guards** (wired by the `hooks` of the project's `.claude/settings.json`; code in `.claude/lib/procs/build/guards.py`;
the permission allowlist is the same `.claude/settings.json`) enforce
the checkpoints mechanically while a ticket is `in_progress`: every turn and every session start re-injects the
open ledger lines; an Agent dispatch without an allowed `model` is blocked; writing `plan.md`, `design.md` or any
project file is blocked until a Context7 lookup is recorded in `context7.log` — `plan.md` also until "design
approved" is ticked, `design.md` and project files until "plan approved" is; `git commit` on the default branch is
blocked. A blocked call is a checkpoint you
skipped — do the step, then retry; never route around the guard.

**Update `session.md`:** at the end of Path A (plan and design saved), at every ledger tick,
after significant changes to plan, context or Source Data, on user request, before `/compact` or
`/clear`, on completion.

**Context thresholds:** ~65% → "Context ~65%. Recommend `/compact`. Saving state." and save;
~90% → "Context ~90%. Saving state. Run `/clear`, then `/build-start <ticket-id>`."
Before `/compact` or `/clear` — **mandatory, and before the threshold**: the PreCompact hook of this procedure
reminds on both a manual `/compact` and an automatic one, but a reminder is not a substitute for saving in time. Update `session.md`
(step, progress, uncommitted files, ledger), make sure `clarifications.md` holds every qualifying
entry from this conversation, confirm to the user that state is saved.

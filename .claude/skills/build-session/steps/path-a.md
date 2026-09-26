# Path A: New Ticket — full protocol

Read before starting Path A of the `build-session` skill, and again in every fresh context (`/compact`, `/clear`, `/new`, a new launch) while Path A is unfinished. Steps marked **⏹** are ledger checkpoints (build-session `## Ticket state`).

1. Source Data and ticket loaded by `/build-start`.

2. **The state files.**
   - Create `.build-state/<TICKET-ID>/session.md` and `clarifications.md` from the templates
     (`## Ticket state`): run
     `python3 .claude/bin/procs build scaffold <TICKET-ID> --layer <layer>`
     (`<layer>` = the LAYER line of `/build-start`).
     Status is `in_progress` from creation — the command sets it in Metadata; it never overwrites an existing file.
     Then fill in what only you know: the ticket's short description and Task Context (Branch — at step 5).

3. **Explore** — launch 2–3 `feature-dev:code-explorer` agents in parallel (`## Subagents`,
   `low_model`), each on a different aspect: entry points and direct dependencies of the ticket;
   similar features/patterns and how they are implemented; test coverage and test patterns of
   the affected modules. Read every key file they identify before the design dialogue.

4. **Design exploration** — collaborative dialogue turning the ticket into an approved design.
   No code, no implementation skill, no plan writing until the user approves the design.
   - Clarify one question at a time: purpose, constraints, success criteria; multiple-choice when
     possible. Discrepancies and principal decisions as they arise → clarifications.md.
   - ⏹ **Context7 — design**: every framework/library the design will touch, before proposing
     approaches.
   - Propose 2–3 approaches with trade-offs, recommended option first. For a broad design space
     dispatch 3 parallel `feature-dev:code-architect` agents (`high_model`): minimal changes
     (smallest footprint, maximum reuse) / clean architecture (maintainability, abstractions) /
     pragmatic balance (speed + quality, fits team context).
   - Present the design in sections scaled to complexity (architecture, components, data flow,
     error handling, testing); get approval section by section.
   - Self-review before locking: placeholders (TBD/TODO/vague), internal consistency, scope
     (one plan or decomposition), ambiguity (two readings → pick one explicitly). Fix inline, no
     re-review.
   - Do **not** write `design.md` yet — it is saved once the plan derived from it is approved.

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

7. **Plan** — write `.build-state/<TICKET-ID>/plan.md` per `plan.template.md` (header, task
   structure in the chosen testing variant, granularity and no-placeholder rules).
   - Scope check first: multiple independent subsystems → suggest one plan per subsystem, each
     producing working, testable software on its own.
   - Map the file structure before defining tasks: which files to create or modify, one
     responsibility each, following established codebase patterns.
   - ⏹ **Context7 — plan**: every library whose code appears in the plan.
   - Self-review before presenting: spec coverage (a task for every requirement of the approved
     design), placeholders, type and method-name consistency across tasks. Fix inline.

8. Review the plan with the user → clarifications.md.

9. **Save the design** to `.build-state/<TICKET-ID>/design.md` (the sections presented at the
   design step). Update `session.md`: artifacts, progress, ledger.

---
name: build-status
description: Show the state of one build ticket, or the list of the project's tickets.
argument-hint: "[ticket-id]"
---

# Build Status

Show ticket state or list of active tickets. The facts are computed — word them, do not recount them:

```!
python3 .claude/bin/procs build status --project "${CLAUDE_PROJECT_DIR}" <<'__PROCS_ARGS__'
$ARGUMENTS
__PROCS_ARGS__
```

## No argument: `/build-status`

Show all tickets in `.build-state/` (`step 3/5` = the `plan.md` step being worked on, of its total):

```
📋 Active tickets:
  TICKET-42 — description (step 3/5, branch feature/TICKET-42-...)
  TICKET-43 — description (step 1/4, branch feature/TICKET-43-...)

✅ Completed:
  TICKET-41 — description
```

For each — output status and progress briefly (`progress (session.md)` is the ticket's own note of where it is).

## With argument: `/build-status TICKET-42`

Output, taking Done / Current / Remaining from PLAN STEPS and `progress (session.md)`; for `N entries` read
the `clarifications.md` named in the facts:

```
📋 Ticket: TICKET-42 — description
🌿 Branch: feature/TICKET-42-short-name
📊 Status: in_progress
📅 Session: #2

✅ Done:
  1. [x] Step — description
  2. [x] Step — description

🔄 Current:
  3. [ ] Step — description

⏳ Remaining:
  4. [ ] Step — description

📝 Clarifications: N entries
📁 Uncommitted: M files
```

If ticket not found — report.

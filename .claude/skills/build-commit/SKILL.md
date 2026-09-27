---
name: build-commit
description: Review → commit → push → PR → CI → squash-merge for the current build ticket, run unattended on a feature branch.
argument-hint: "[ticket-id]"
---

# Build Commit

Review → commit → push → PR → merge. Runs for the current ticket.
Applies to feature branches only — stop if current branch is the default branch
(`main` / `master` / `develop` — whichever the spec's CI/CD section names).

**Autonomy — do NOT ask for step-by-step approval.** The user's invocation of `/build-commit` IS the approval to
run the entire flow (commit → push → PR → squash-merge) to completion. Execute Steps 4–8 directly, without
confirmation prompts. Two kinds of interactive pause remain:
- **(a) a check surfaces a problem needing a fix decision** — `code-review` findings (Step 2), failing tests
  (Step 1), or failing CI (Step 7): propose fixes and wait for the user.
- **(b) staging is the user's own act (Step 4)** — `git add` is under the global `permissions.deny`, so the agent
  cannot stage anything. It prints the exact `git add` line for the user to run, waits, and verifies what was staged;
  that is the user's sign-off on the fileset. `git commit` IS allowlisted and runs unprompted.

Otherwise a clean run commits, opens the PR, and squash-merges with no `/build-commit`-issued questions.

## Step 0 — Identify Ticket

```!
python3 .claude/bin/procs build status --project "${CLAUDE_PROJECT_DIR}" <<'__PROCS_ARGS__'
$ARGUMENTS
__PROCS_ARGS__
```

If argument provided (`/build-commit TICKET-42`) — use it. If not — use the single ticket under `ACTIVE:`.
If multiple `in_progress` tickets — ask which one. If zero — report no active tickets.
Verify there are uncommitted changes (`git status`).

Models: per build-session `## Models`. Never let a subagent inherit the main-loop model.

## Step 1 — Tests

Run `test-runner` (`model` = `low_model`). Process results. If errors — propose fixes. Repeat until green.

## Step 2 — Code Review

Dispatch a `general-purpose` subagent with the Agent tool `model` set to `high_model`. Its task: invoke the
built-in `code-review` skill with args `scope: the current git diff, plus these specs, each read in full: <SPEC>,
<dependency specs>` at effort level `high` (or the level the user asked for), fix nothing, and return every finding
verbatim — file, line, summary, failure scenario. Substitute real file paths before dispatching — never pass the
placeholders or a description in their place: `<SPEC>` is the spec `/build-start` located; `<dependency specs>` are
the specs it references as dependencies (e.g. a platform frame spec, specs of the shared libraries it uses).
Present the findings to the user unchanged; the user picks what to fix and what to skip. Apply only the chosen
fixes, then repeat Step 1 and Step 2 on the updated diff — until the review reports nothing or the user accepts
what's left.

## Step 3 — Local Checks

Run the project's local-check suite as fixed in the spec's **CI/CD + conventions** section (stage 13) — lint,
format, static types, secret/credential scan. These are wired through the project's task runner or pre-commit
framework; run whichever the project defines, e.g.:

```bash
# pick the one the project uses (see CONTRIBUTING.md / Makefile / pyproject / package.json):
pre-commit run --all-files        # pre-commit framework
make check                        # Makefile target
task check                        # Taskfile / just / npm run check / …
```

Fix any failures and re-run until clean. These must mirror the checks CI runs.

## Step 4 — Commit

Generate the commit message per the Commit Messages convention in `./CONTRIBUTING.md` (or the spec's §13 CI/CD
conventions if no `CONTRIBUTING.md` exists). The commit subject/body are **in English** (per build-session
`## Language`).

Staging is the user's act — `git add` is denied to the agent (see (b)). In one message:
1. print ONE `git add <explicit paths>` line — every path spelled out, respecting .gitignore; never `-A`, `.` or `-u`;
2. ask the user to run it (in this session `!` before the line runs it as typed);
3. when the user reports it done, run `git diff --cached --name-only` and compare with the list you printed. A
   difference is not an error: name it and let the user decide whether to stage the rest or commit what is staged;
4. then execute `git commit` with the message and **no pathspec** — do NOT ask for confirmation (it is allowlisted),
   and never `git commit -a` / `--all` / `git commit <path>`: those would decide the fileset for the user.

## Step 5 — Push

Execute push.

## Step 6 — Create PR

Read `.github/pull_request_template.md` (or the PR template the spec's CI/CD section names; if neither exists on
disk, use the spec's PR-template structure). Fill all sections from the ticket context. **The PR title
and body MUST be in English** (per build-session `## Language`), regardless of the dialogue language — translate
working notes if needed. Create the PR directly — do NOT ask for confirmation. Execute:
```bash
gh pr create --title "<title>" --body "<filled template>"
```
Report PR URL.

## Step 7 — Monitor CI

Stream the checks for the **current branch's** PR (no hardcoded repo or run id):

```bash
gh pr checks --watch        # blocks until all checks settle
# or, for a one-shot snapshot:  gh pr checks
```

- All checks pass → proceed to Step 8.
- Any check fails:
  1. Get failure details: `gh run view --log-failed` (or open the failing check from `gh pr checks`).
  2. Analyze root cause from logs.
  3. Propose concrete fix to user; wait for approval.
  4. After fix — return to Step 1 (re-run tests, review, local checks, commit, push).
  5. CI re-runs automatically on new push; repeat this step.

## Step 8 — Squash Merge and Delete Branch

```bash
gh pr merge --squash --delete-branch
```

Execute the squash-merge directly — do NOT ask for confirmation. Verify it completed; report ticket done.

## Step 9 — Return

Return to the build session protocol corresponding step if was run from the build-session skill, or exit if run
standalone.

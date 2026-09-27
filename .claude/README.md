# `build` — the holahost development protocol

Ticket routing, ticket state, the protocol ledger and its guards. The procedure is project-local: its skills, agent,
hooks and permissions live in this repository's `.claude/` and take effect only when Claude Code is started from its root.

## What's inside

| Path | What it is |
|---|---|
| `settings.json` | the session's model and effort (`opus` / `xhigh`), toolchain permissions, guard hooks |
| `settings.local.json` | personal rules and absolute paths; not versioned |
| `skills/build-session/` | `/build-session <ticket-id…> <layer>` — the protocol, from the route (START / STOP / ASK) and the spec sections on; next to it the state and plan templates; the subagents' `## Models` table |
| `skills/build-commit/` | `/build-commit` — tests, review, local checks, commit, push, PR, CI, squash-merge |
| `agents/test-runner.md` | a subagent; its `model` is only the default, a dispatch always passes `model` explicitly |
| `bin/procs` | CLI of the build domain: `python3 .claude/bin/procs build …` from the project root — exactly the spelling the rule in `settings.json` names |
| `bin/procs-hook` | hook entrypoint: kill switch → self-gate on `.build-state` → library import |
| `lib/procs/` | the library: `build/` (route, status, scaffold, guards), `core/` (ledger, markdown sections, paths) |

## Model and permissions

- Model and effort are the `model` / `effortLevel` keys in `settings.json`: they apply for the whole session. A skill's
  frontmatter (`model`, `effort`, `allowed-tools`) applies for one turn only, so it is not used here.
- Subagent models are the `## Models` table in `skills/build-session/SKILL.md`; the `agent-model` hook blocks an Agent
  call whose `model` differs from its row, or whose type has no row, while a ticket is `in_progress`.
- The gate on what goes into a commit is in the global `~/.claude/settings.json`: `git add` is under `deny`, a human
  stages (`skills/build-commit/SKILL.md`, step 4).

## Kill switch

Guards only, immediately and everywhere: `touch ~/.claude/procs.guards.off` (or `PROCS_GUARDS=off` in the environment).
The file is checked first thing in `bin/procs-hook`, before the library is imported. Without a `.build-state/`
directory the guards stay silent.

## Checks after edits

The procedure has no tests. The minimum after any edit, from the project root:

```bash
python3 -m py_compile $(find .claude/lib -name '*.py')
python3 .claude/bin/procs build status
echo '{"hook_event_name":"PreToolUse","tool_name":"Agent","tool_input":{"subagent_type":"x"}}' \
  | CLAUDE_PROJECT_DIR=$PWD python3 -I -S .claude/bin/procs-hook agent-model   # with a ticket in_progress — exit 2
```

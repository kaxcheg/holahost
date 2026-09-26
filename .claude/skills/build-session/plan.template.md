# Plan template — `.build-state/<TICKET-ID>/plan.md`

Read at the Plan step of the build-session protocol. Use the project's language, test framework
and run commands from the spec's Tech Constraints (stack) and CI/CD (test/lint/type commands)
sections; the examples below are stack-neutral — substitute the project's real syntax.

## Header

```markdown
# [ Ticket ] Implementation Plan

**Goal:** [one sentence]
**Architecture:** [2-3 sentences]
**Tech Stack:** [key libraries]
---
```

## Task structure

Checkbox syntax for tracking. Use the variant matching the testing approach chosen for the
ticket (TDD / code-first; mixed = per task).

### TDD variant

````markdown
### Task N: [Component Name]

**Files:**
- Create: `<path/to/source-file>`
- Test: `<path/to/test-file>`

- [ ] **Step 1: Write the failing test**
```
test "specific behavior":
    result = function(input)
    assert result == expected
```
- [ ] **Step 2: Run to verify it fails**
Run: `<project test command + selector>`   # e.g. pytest path::name -v · npm test -- path · go test -run Name ./...
Expected: FAIL with "..."
- [ ] **Step 3: Write minimal implementation**
```
function(input): ...
```
- [ ] **Step 4: Run to verify it passes**
Run: `<project test command + selector>`
Expected: PASS
````

### Code-first variant

````markdown
### Task N: [Component Name]

**Files:**
- Create: `<path/to/source-file>`
- Test: `<path/to/test-file>`

- [ ] **Step 1: Implement**
```
function(input): ...
```
- [ ] **Step 2: Write tests**
```
test "specific behavior":
    result = function(input)
    assert result == expected
```
- [ ] **Step 3: Run to verify tests pass**
Run: `<project test command + selector>`
Expected: PASS
````

## Rules

- **Step granularity:** 2–5 minutes per step, one action each. Actual code in every code step.
  Exact commands with expected output. No commit steps — `/build-commit` handles all commits.
- **No placeholders:** never TBD, TODO, "implement later", "similar to Task N", "add error
  handling" without specifics, "write tests for the above" without actual test code. Every step
  contains what an engineer needs to act on it.

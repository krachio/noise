---
active: true
iteration: 3
max_iterations: 20
completion_promise: null
started_at: "2026-03-21T23:46:09Z"
---

You are reviewing and refactoring this codebase. Each iteration you do ALL of these steps:

## Step 0: Ground yourself
Run /remind. This loads the coding principles you MUST follow. Do this before touching any code.

## Step 1: Review
Read CODING_STYLE.md. Then systematically read source files and find CONCRETE issues:
- Bugs, logic errors, race conditions, undefined behavior
- Wrong abstraction level, leaky interfaces, hidden coupling
- Copy-paste duplication, dead code, cargo-culted patterns
- Hot patches that paper over deeper design problems
- Allocations on hot paths, cache-hostile layouts, unnecessary indirection
- Violations of CODING_STYLE.md

Do NOT flag: missing comments, naming nitpicks, or speculative refactors.
Check git log for [ralph-iter-*] commits to avoid re-flagging already-fixed issues.

## Step 2: Plan
Pick the top 3-5 most impactful fixes. Write a checklist to .ralph-review/sprint.md:
```
- [ ] SHORT_TITLE — file:line — what to fix
```

## Step 3: Execute
Run /remind again before writing any code.
For each item: fix it, run tests (cargo test --workspace / uv run pytest), commit as "refactor(module): description [ralph-iter-N]". Mark [x] when done.
If tests fail after 3 attempts, leave unchecked with a note.

If two consecutive iterations produce zero new findings, output <promise>CONVERGED</promise>.

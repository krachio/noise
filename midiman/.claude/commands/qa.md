---
name: qa
description: Run type checker + tests + critical QA review of test quality
user_invocable: true
---

Read the Stack section of CLAUDE.md to determine the type checker and test runner for this project.

Run the following checks sequentially. Stop and report on the first failure.

## 1. Type Checker

Run the type checker specified in CLAUDE.md's Stack section.

If it reports any errors, stop and report them. Do not proceed.

## 2. Test Runner

Run the test runner specified in CLAUDE.md's Stack section.

If any tests fail, stop and report them. Do not proceed.

## 3. Critical QA Review

After both tools pass, review ALL test files. Evaluate each test critically:

- **Real behavior**: Does the test verify actual behavior and outputs, or just restate types/structure?
- **Mock quality**: If mocks are used, do they test real integration points or just cosplay interactions?
- **Edge cases**: Are failure modes and boundary conditions covered?
- **Meaningfulness**: Would the test catch a real regression, or would it pass even with a broken implementation?

Flag any test that fails these criteria as a **slop test** and recommend specific improvements.

## Reporting

Output a summary:
- Type checker: PASS/FAIL
- Tests: PASS/FAIL (N tests)
- Test quality: PASS/CONCERNS (list any slop tests found)

Block progress (report failure) if type checking fails, tests fail, or slop tests are found.

Strict TDD: Tests pin intended behavior before implementation proceeds. Never write implementation code without tests that define the expected behavior first.

Tests must verify real behavior. Reject:
- Property-existence checks (testing that a field exists rather than its value)
- Trivial type-following tests (asserting isinstance without behavioral checks)
- Mock-heavy tests that don't verify real behavior

Tests must cover edge cases and failure modes.

When encountering a bug: ALWAYS write a failing test FIRST that reproduces
the bug, THEN fix the implementation until the test passes. Never fix a bug
without a regression test that would catch it if it returned.

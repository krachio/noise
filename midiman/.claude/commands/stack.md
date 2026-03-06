---
name: stack
description: Configure project stack - fill in CLAUDE.md, set up tooling, initial commit
user_invocable: true
---

Configure this project's language-specific tooling.

## Input

Read `.claude/init-prompt`. It contains the project name and complete stack specification. If the file does not exist, ask the user for the stack description — but do NOT proceed until you have all of: language/version, type checker, test runner, and package manager.

## Steps

1. **Parse the init-prompt**: Extract project name, language, version, type checker, test runner, package manager. Do NOT prompt for clarification if the init-prompt provides all required fields.

2. **Fill in CLAUDE.md**: Replace `<Project>` in the title with the project name. Fill in the Stack section with concrete values and commands (e.g., the exact commands `/qa` should run).

3. **Set up tooling**:
   - Initialize the package manager config if needed (e.g., `pyproject.toml`, `package.json`, `Cargo.toml`)
   - Configure the type checker for strict mode
   - Configure the test runner
   - Create a `.pre-commit-config.yaml` with local hooks for the type checker and test runner
   - Create the test directory scaffold
   - Install dependencies
   - Install pre-commit hooks

4. **Update PROGRESS.md** to reflect the configured state.

5. **Delete `.claude/init-prompt`**.

6. **Commit incrementally** following the iteration protocol:
   - Commit 1: CLAUDE.md with filled-in stack
   - Commit 2: Package config + dependencies
   - Commit 3: Pre-commit config + hooks
   - Commit 4: Test scaffold

After completion, report what was set up and confirm `/qa` passes.

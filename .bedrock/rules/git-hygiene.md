The repository is the product. A clean repo earns trust; a messy one erodes it.

## What belongs in the repo
- Source code (Rust, Python, FAUST)
- Build configuration (Cargo.toml, pyproject.toml, Cargo.lock at workspace root)
- Documentation source (docs/*.md, mkdocs.yml, README.md, CLAUDE.md)
- CI/CD workflows (.github/)
- Coding rules (.bedrock/rules/)
- A single PROGRESS.md at the repo root

## What does NOT belong
- Build artifacts (target/, site/, dist/, *.whl, *.egg-info)
- Virtual environments (.venv/, node_modules/)
- Lock files in subcrates (only workspace-root Cargo.lock is tracked)
- Binary files (wheels, compiled assets, fonts, images unless essential)
- Per-subcrate scaffolding (.bedrock/, .claude/, .pre-commit-config.yaml — only top-level)
- Planning/iteration artifacts (plan.md, reviewers.md, ralph loop state)
- Frontend/deployment code that has a different release cycle (web REPL, landing pages)
- IDE/editor config (.vscode/, .idea/) except shared formatter settings
- Stale backward-compat shims — delete them, don't accumulate

## Commit discipline
- Every commit must pass pre-commit hooks (cargo check/test/clippy, ruff, pyright, pytest)
- Self-contained examples in docs — no undefined references
- Terminology must be consistent across code, docs, tests, error messages, and comments
- When renaming a concept: grep the entire repo and fix every occurrence, including test docstrings and doc pages
- Never commit a file "to fix later" — fix it now or don't commit it

## Pre-commit hooks are mandatory
The repo has a global .pre-commit-config.yaml. Run `pre-commit install` after cloning.
If a hook fails, fix the issue — do not bypass with --no-verify.

# Progress

## Current state

Stack configured and tooling bootstrapped:
- Python 3.12 (pinned via `.python-version`)
- pyright strict (configured in `pyproject.toml`)
- pytest with `tests/` scaffold
- uv for package management (`pyproject.toml` + `uv.lock`)
- pre-commit hooks: pyright + pytest run on every commit

## Next

- Implement project features (no domain logic yet)

# Progress

## Current state

Stack configured and tooling bootstrapped:
- Language: Python 3.13
- Package manager: uv (`.venv` created, `uv.lock` committed)
- Type checker: pyright strict (configured in `pyproject.toml`)
- Test runner: pytest (testpaths = `tests/`)
- Pre-commit hooks: pyright + pytest (installed at `.git/hooks/pre-commit`)
- Test scaffold: `tests/__init__.py` + `tests/test_placeholder.py`

## Next

- Define the faust-dsl domain model and grammar
- Remove placeholder test once real tests exist

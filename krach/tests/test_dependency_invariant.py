"""Verify ir/ is a pure data layer with no runtime dependencies.

ir/ must not import (at module level) from krach.signal, krach.pattern,
or krach.backends. Lazy imports inside function bodies are fine (JAX pattern).
"""

from __future__ import annotations

import ast
import pathlib


IR_DIR = pathlib.Path(__file__).resolve().parent.parent / "src" / "krach" / "ir"
BANNED_PREFIXES = ("krach.signal", "krach.pattern", "krach.backends", "krach.dsl")


def _collect_module_level_imports(source: str) -> list[tuple[int, str]]:
    """Return (lineno, module) for each module-level import statement."""
    tree = ast.parse(source)
    violations: list[tuple[int, str]] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if any(node.module.startswith(b) for b in BANNED_PREFIXES):
                violations.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name.startswith(b) for b in BANNED_PREFIXES):
                    violations.append((node.lineno, alias.name))
    return violations


def test_ir_no_module_level_imports_from_runtime() -> None:
    """ir/ files must not import from signal/, pattern/, or backends/ at module level."""
    all_violations: list[str] = []
    for py_file in sorted(IR_DIR.glob("*.py")):
        source = py_file.read_text()
        violations = _collect_module_level_imports(source)
        for lineno, mod in violations:
            all_violations.append(f"{py_file.name}:{lineno} imports {mod}")
    assert all_violations == [], (
        "ir/ has banned module-level imports:\n" + "\n".join(all_violations)
    )

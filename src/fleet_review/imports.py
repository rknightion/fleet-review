"""Which lines of a source file are import lines (used to drop import-only clones)."""

from __future__ import annotations

import ast
import re

_GO_IMPORT = re.compile(r"^\s*import(?:\s|\()")


def go_import_lines(source: str) -> set[int]:
    """Line-based: an `import` declaration, or every line of an `import ( ... )` block."""
    out: set[int] = set()
    in_block = False
    for n, line in enumerate(source.splitlines(), start=1):
        if in_block:
            out.add(n)
            if line.strip().startswith(")"):
                in_block = False
        elif _GO_IMPORT.match(line):
            out.add(n)
            code = line.split("//", 1)[0]
            if "(" in code and ")" not in code.split("(", 1)[1]:
                in_block = True
    return out


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def py_import_lines(source: str) -> set[int]:
    """Import statements (multi-line included), plus `if TYPE_CHECKING:` blocks of only imports."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom) or (
            isinstance(node, ast.If)
            and _is_type_checking(node.test)
            and not node.orelse
            and all(isinstance(b, ast.Import | ast.ImportFrom) for b in node.body)
        ):
            out.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return out


def import_lines(path: str, source: str) -> set[int]:
    if path.endswith(".go"):
        return go_import_lines(source)
    if path.endswith(".py"):
        return py_import_lines(source)
    return set()

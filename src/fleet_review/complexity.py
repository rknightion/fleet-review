"""Complexity check: lizard on base and head versions of changed files."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass

import lizard

from fleet_review.config import Config
from fleet_review.gitutil import Change
from fleet_review.model import CheckResult, finding_id


@dataclass(frozen=True)
class Func:
    name: str
    ccn: int
    start: int
    end: int


_ANON = re.compile(r"^anonymous(__\d+)?$")


def go_receiver(long_name: str) -> str:
    """The receiver type of a Go method from lizard's long name, or "".

    lizard renders `func (t *T) Name(...)` as `(t*T)Name ...` and `func (u U) Name()` as
    `(u U)Name`. Pointer-ness, the receiver variable and type arguments are dropped, so the
    receiver is the bare type name.
    """
    if not long_name.startswith("("):
        return ""
    depth = 0
    for i, ch in enumerate(long_name):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0:
            inner = long_name[1:i]
            break
    else:
        return ""
    # Cut type arguments first: `g *Gen[K, V]` -> `g *Gen`.
    lb = inner.find("[")
    if lb != -1:
        inner = inner[:lb]
    inner = inner.strip()
    if "*" in inner:
        inner = inner.split("*", 1)[1]
    elif " " in inner:
        inner = inner.split()[-1]
    return inner.strip()


def _python_classes(source: str) -> list[tuple[str, int, int]]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    out: list[tuple[str, int, int]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qual = f"{prefix}{child.name}"
                out.append((qual, child.lineno, child.end_lineno or child.lineno))
                walk(child, qual + ".")
            else:
                walk(child, prefix)

    walk(tree, "")
    return out


def analyze(path: str, source: str) -> dict[str, Func]:
    """Functions of one file keyed by a stable identity.

    Identity is the name without its parameter list, qualified by the Go receiver type or the
    Python class. Anonymous functions are folded into the enclosing named function by line
    range: their complexity is added to it and their positional names are never used.
    """
    info = lizard.analyze_file.analyze_source_code(path, source)
    functions = list(info.function_list)
    classes = _python_classes(source) if path.endswith(".py") else []

    named: list[tuple[str, int, int, int]] = []  # qualified name, ccn, start, end
    anons = []
    for fn in functions:
        if _ANON.match(fn.name):
            anons.append(fn)
            continue
        if path.endswith(".go"):
            recv = go_receiver(fn.long_name)
            name = f"{recv}.{fn.name}" if recv else fn.name
        elif classes:
            enclosing = [c for c in classes if c[1] <= fn.start_line and fn.end_line <= c[2]]
            enclosing.sort(key=lambda c: c[2] - c[1])
            name = f"{enclosing[0][0]}.{fn.name}" if enclosing else fn.name
        else:
            name = fn.name
        named.append((name, fn.cyclomatic_complexity, fn.start_line, fn.end_line))

    extra = [0] * len(named)
    for a in anons:
        best = None
        for i, (_, _, s, e) in enumerate(named):
            if (
                s <= a.start_line
                and a.end_line <= e
                and (best is None or e - s < named[best][3] - named[best][2])
            ):
                best = i
        if best is not None:
            extra[best] += a.cyclomatic_complexity - 1

    out: dict[str, Func] = {}
    seen: dict[str, int] = {}
    for (name, ccn, start, end), add in sorted(
        zip(named, extra, strict=True), key=lambda t: t[0][2]
    ):
        # Repeated names in one file (several Go `init`s, Python property setters) are
        # told apart by occurrence order.
        n = seen.get(name, 0) + 1
        seen[name] = n
        key = name if n == 1 else f"{name}#{n}"
        out[key] = Func(key, ccn + add, start, end)
    return out


def check(
    cfg: Config,
    root,
    changes: list[Change],
    read_base: Callable[[str], str | None],
) -> CheckResult:
    res = CheckResult("complexity")
    analysed = 0
    for ch in changes:
        if not cfg.in_scope(ch.path):
            continue
        try:
            head_src = (root / ch.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        analysed += 1
        head = analyze(ch.path, head_src)
        base_src = read_base(ch.base_path) if ch.base_path else None
        base = analyze(ch.base_path, base_src) if base_src is not None else {}
        for name, fn in head.items():
            old = base.get(name)
            if old is None:
                if fn.ccn > cfg.new_function_ccn:
                    res.findings.append(_finding("new_over_threshold", ch.path, fn, None, cfg))
            elif fn.ccn - old.ccn >= cfg.min_ccn_delta:
                res.findings.append(_finding("grown", ch.path, fn, old.ccn, cfg))
    res.detail = f"{analysed} changed file{'s' if analysed != 1 else ''} analysed"
    return res.finalize()


def _finding(kind: str, path: str, fn: Func, base_ccn: int | None, cfg: Config) -> dict:
    if kind == "grown":
        msg = f"{path} {fn.name}: CCN {base_ccn} -> {fn.ccn} (+{fn.ccn - base_ccn})"
    else:
        msg = f"{path} {fn.name}: new function with CCN {fn.ccn} (limit {cfg.new_function_ccn})"
    return {
        "id": finding_id("complexity", path, fn.name),
        "check": "complexity",
        "kind": kind,
        "file": path,
        "function": fn.name,
        "line": fn.start,
        "base_ccn": base_ccn,
        "head_ccn": fn.ccn,
        "message": msg,
    }

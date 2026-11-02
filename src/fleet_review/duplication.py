"""Duplication check: jscpd clones that touch a changed line."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fleet_review import complexity, gitutil, imports
from fleet_review.config import Config
from fleet_review.gitutil import Change
from fleet_review.model import CheckResult, finding_id

DEFAULT_JSCPD_VERSION = "5.4.2"
TIMEOUT_SECONDS = 600
# jscpd also gates on a token floor (default 50), which would hide short clones that the
# user's min_clone_lines asks for. Scale the floor with the line threshold instead.
TOKENS_PER_LINE = 3


@dataclass(frozen=True)
class Side:
    file: str
    start: int
    end: int


def resolve_jscpd(version: str) -> tuple[list[str] | None, str]:
    """The command prefix for jscpd, or (None, reason).

    A `jscpd` on PATH is used only when its `--version` equals the pin.
    """
    exe = shutil.which("jscpd")
    if exe:
        try:
            out = subprocess.run(
                [exe, "--version"], capture_output=True, text=True, timeout=60, check=False
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        if out.split()[-1:] == [version]:
            return [exe], ""
    npx = shutil.which("npx")
    if npx:
        return [npx, "-y", f"jscpd@{version}"], ""
    return None, f"jscpd {version} unavailable (no matching jscpd on PATH and npx not found)"


# Beyond this many characters of file arguments, scan the source roots instead and filter after.
MAX_ARG_CHARS = 120_000


def run_jscpd(
    cmd: list[str], root: Path, cfg: Config, targets: list[str]
) -> tuple[list[dict] | None, str]:
    with tempfile.TemporaryDirectory(prefix="fleet-review-") as tmp:
        args = [
            *cmd,
            "--min-lines",
            str(cfg.min_clone_lines),
            "--min-tokens",
            str(cfg.min_clone_lines * TOKENS_PER_LINE),
            "--format",
            "go,python",
            "--workers",
            "1",
            "--absolute",
            "--no-tips",
            "--no-colors",
            "--reporters",
            "json",
            "--output",
            tmp,
        ]
        args += targets
        env = {**os.environ, "NO_COLOR": "1", "JSCPD_NO_TIPS": "1"}
        try:
            proc = subprocess.run(
                args,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, f"jscpd timed out after {TIMEOUT_SECONDS}s"
        except OSError as e:
            return None, f"jscpd could not start: {e}"
        report = Path(tmp) / "jscpd-report.json"
        if proc.returncode != 0 or not report.is_file():
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            return None, f"jscpd failed (exit {proc.returncode}): {' | '.join(tail)}"
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return None, f"jscpd report unreadable: {e}"
    return data.get("duplicates", []), ""


def _rel(name: str, roots: list[Path]) -> str | None:
    p = Path(name)
    if not p.is_absolute():
        return p.as_posix()
    for r in roots:
        try:
            return p.relative_to(r).as_posix()
        except ValueError:
            continue
    return None


def check(
    cfg: Config,
    root: Path,
    changes: list[Change],
    jscpd_version: str,
    *,
    resolver: Callable[[str], tuple[list[str] | None, str]] | None = None,
) -> CheckResult:
    cmd, why = (resolver or resolve_jscpd)(jscpd_version)
    if cmd is None:
        return CheckResult.skipped("duplication", why)
    changed = {c.path: c.lines for c in changes if cfg.in_scope(c.path)}
    if not changed:
        return CheckResult("duplication", detail="no changed source files in scope").finalize()
    # Scan exactly the in-scope files. jscpd's own --ignore globs match absolute paths with a
    # `*` that crosses `/`, so `test_*.py` would drop every file under a `test_foo/` checkout.
    files = [f for f in gitutil.list_files(root) if cfg.in_scope(f)]
    if sum(len(f) + 1 for f in files) > MAX_ARG_CHARS:
        files = [p for p in cfg.paths if (root / p).exists()]
    if not files:
        return CheckResult.skipped("duplication", "no source files in the configured paths")

    clones, why = run_jscpd(cmd, root, cfg, files)
    if clones is None:
        return CheckResult.skipped("duplication", why)

    roots = [root.resolve(), root]
    fn_cache: dict[str, dict[str, complexity.Func]] = {}

    src_cache: dict[str, str] = {}

    def source(file: str) -> str:
        if file not in src_cache:
            try:
                src_cache[file] = (root / file).read_text(encoding="utf-8", errors="replace")
            except OSError:
                src_cache[file] = ""
        return src_cache[file]

    def import_only(side: Side) -> bool:
        """Every non-blank changed line of the side that the clone overlaps is an import line."""
        text = source(side.file).splitlines()
        overlapped = [
            n
            for n in sorted(changed[side.file])
            if side.start <= n <= side.end and n <= len(text) and text[n - 1].strip()
        ]
        imps = imports.import_lines(side.file, source(side.file))
        return bool(overlapped) and all(n in imps for n in overlapped)

    def enclosing(file: str, line: int) -> str:
        if file not in fn_cache:
            fn_cache[file] = complexity.analyze(file, source(file))
        best: complexity.Func | None = None
        for fn in fn_cache[file].values():
            if fn.start <= line <= fn.end and (
                best is None or fn.end - fn.start < best.end - best.start
            ):
                best = fn
        return best.name if best else ""

    res = CheckResult("duplication")
    import_only_dropped = 0
    merged: dict[str, dict] = {}
    for c in clones:
        sides: list[Side] = []
        for key in ("firstFile", "secondFile"):
            f = c[key]
            rel = _rel(f["name"], roots)
            if rel is None or not cfg.in_scope(rel):
                break
            sides.append(Side(rel, int(f["start"]), int(f["end"])))
        else:
            hits = [_touches(s, changed) for s in sides]
            if not any(hits):
                continue
            if all(import_only(sd) for sd, h in zip(sides, hits, strict=True) if h):
                import_only_dropped += 1
                continue
            if hits == [False, True]:
                sides.reverse()
                hits.reverse()
            elif hits == [True, True]:
                sides.sort(key=lambda s: (s.file, s.start))
            group = "within_change" if all(hits) else "repeats_existing"
            lines = int(c.get("lines") or (sides[0].end - sides[0].start + 1))
            a, b = sides
            fa, fb = enclosing(a.file, a.start), enclosing(b.file, b.start)
            fid = finding_id("duplication", a.file, fa, b.file, fb)
            entry = {
                "file": a.file,
                "start": a.start,
                "end": a.end,
                "partner": {"file": b.file, "function": fb, "start": b.start, "end": b.end},
                "lines": lines,
            }
            if fid in merged:
                merged[fid]["also"].append(entry)
                continue
            merged[fid] = {
                "id": fid,
                "check": "duplication",
                "group": group,
                "file": a.file,
                "function": fa,
                "start": a.start,
                "end": a.end,
                "partner": entry["partner"],
                "lines": lines,
                "message": _message(a, b, lines),
                "also": [],
            }
    res.findings = sorted(
        merged.values(), key=lambda f: (f["group"] != "within_change", f["file"], f["start"])
    )
    res.detail = f"{len(clones)} clone(s) found by jscpd, {len(res.findings)} touch this change" + (
        f", {import_only_dropped} import-only dropped" if import_only_dropped else ""
    )
    return res.finalize()


def _touches(side: Side, changed: dict[str, set[int]]) -> bool:
    lines = changed.get(side.file)
    return bool(lines) and any(side.start <= n <= side.end for n in lines)


def _message(a: Side, b: Side, lines: int) -> str:
    return f"{a.file}:{a.start}-{a.end} repeats {b.file}:{b.start}-{b.end} ({lines} lines)"

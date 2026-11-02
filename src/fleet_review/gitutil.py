"""Read-only git access. Never checks out, stashes, fetches or writes to the repo."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


class GitError(Exception):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    cmd = ["git", "-c", "core.quotepath=false", "-C", str(root), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except FileNotFoundError as e:
        raise GitError("git is not installed") from e
    if check and proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(msg or f"git {' '.join(args)} failed")
    return proc


def toplevel(path: Path) -> Path:
    if not path.is_dir():
        raise GitError(f"not a directory: {path}")
    proc = _git(path, "rev-parse", "--show-toplevel", check=False)
    if proc.returncode != 0:
        raise GitError(f"not a git repository: {path}")
    return Path(proc.stdout.decode().strip())


def resolve_commit(root: Path, ref: str) -> str:
    proc = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    if proc.returncode != 0:
        raise GitError(f"base ref not found: {ref}")
    return proc.stdout.decode().strip()


def merge_base(root: Path, base_sha: str) -> str:
    proc = _git(root, "merge-base", base_sha, "HEAD", check=False)
    if proc.returncode != 0:
        raise GitError(f"no merge base between {base_sha[:12]} and HEAD")
    return proc.stdout.decode().strip()


def show(root: Path, commit: str, path: str) -> str | None:
    """Content of `path` at `commit`, or None if absent there."""
    proc = _git(root, "show", f"{commit}:{path}", check=False)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


@dataclass
class Change:
    """One file that differs between the merge base and the working tree."""

    path: str  # path in the working tree
    base_path: str | None  # path at the merge base; None for added/untracked files
    lines: set[int] = field(default_factory=set)  # changed (added) line numbers on the new side
    untracked: bool = False


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _parse_raw(data: bytes) -> list[tuple[str, str, str | None]]:
    """Parse `git diff --raw -z` into (status, new_path, old_path)."""
    toks = data.decode("utf-8", "replace").split("\0")
    out: list[tuple[str, str, str | None]] = []
    i = 0
    while i < len(toks):
        meta = toks[i]
        if not meta.startswith(":"):
            i += 1
            continue
        status = meta.split(" ")[-1]
        if status[0] in "RC":
            out.append((status[0], toks[i + 2], toks[i + 1]))
            i += 3
        else:
            out.append((status[0], toks[i + 1], None))
            i += 2
    return out


def _parse_hunks(text: str) -> dict[str, set[int]]:
    lines_by_path: dict[str, set[int]] = {}
    current: set[int] | None = None
    for line in text.splitlines():
        if line.startswith("+++ "):
            target = line[4:].split("\t")[0]
            if target == "/dev/null":
                current = None
            else:
                target = target.removeprefix("b/").strip('"')
                current = lines_by_path.setdefault(target, set())
        elif line.startswith("@@") and current is not None:
            m = _HUNK.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) is not None else 1
                current.update(range(start, start + count))
    return lines_by_path


def changes_since(root: Path, mb: str) -> list[Change]:
    """Tracked changes of the working tree against `mb`, plus untracked non-ignored files."""
    raw = _git(root, "diff", "--raw", "-z", "-M", "--no-ext-diff", mb).stdout
    diff = _git(
        root,
        "diff",
        "-U0",
        "-M",
        "--no-color",
        "--no-ext-diff",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        mb,
    ).stdout.decode("utf-8", "replace")
    hunks = _parse_hunks(diff)

    changes: dict[str, Change] = {}
    for status, path, old in _parse_raw(raw):
        if status == "D":
            continue
        base_path = path if status == "M" else None
        if status in "RC":
            base_path = old
        if status == "T":
            continue
        changes[path] = Change(path=path, base_path=base_path, lines=hunks.get(path, set()))
        if status == "A":
            # Added files carry every line as changed even when the diff is empty.
            changes[path].lines = _all_lines(root / path)

    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z").stdout
    for path in untracked.decode("utf-8", "replace").split("\0"):
        if not path or path in changes:
            continue
        f = root / path
        if f.is_symlink() or not f.is_file():
            continue
        changes[path] = Change(path=path, base_path=None, lines=_all_lines(f), untracked=True)
    return sorted(changes.values(), key=lambda c: c.path)


def _all_lines(file: Path) -> set[int]:
    try:
        n = len(file.read_bytes().splitlines())
    except OSError:
        return set()
    return set(range(1, n + 1))


def list_files(root: Path) -> list[str]:
    """Tracked plus untracked non-ignored files that exist in the working tree."""
    out = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z").stdout
    paths = {p for p in out.decode("utf-8", "replace").split("\0") if p}
    return sorted(p for p in paths if (root / p).is_file() and not (root / p).is_symlink())

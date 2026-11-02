"""Small glob matcher for the `exclude` setting (supports `**`)."""

from __future__ import annotations

import fnmatch
import re
from functools import lru_cache


@lru_cache(maxsize=256)
def _regex(pattern: str) -> re.Pattern[str]:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                out.append(pattern[i : j + 1])
                i = j
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, pattern: str) -> bool:
    """Whether a repo-relative posix path matches one exclude glob.

    * `name/` matches any directory called `name` anywhere in the path
      (`a/b/` matches the directory path `a/b` anywhere).
    * A pattern without `/` matches the file's base name.
    * Any other pattern is matched against the whole path, and against
      every parent directory of the path (so `src/gen` excludes `src/gen/x.go`).
    """
    parts = path.split("/")
    if pattern.endswith("/"):
        d = pattern.rstrip("/").lstrip("/")
        if "/" not in d:
            return any(fnmatch.fnmatchcase(p, d) for p in parts[:-1])
        rx = _regex("**/" + d)
        return any(rx.match("/".join(parts[:i])) for i in range(1, len(parts)))
    if "/" not in pattern:
        return fnmatch.fnmatchcase(parts[-1], pattern)
    rx = _regex(pattern.lstrip("/"))
    return any(rx.match("/".join(parts[:i])) for i in range(1, len(parts) + 1))


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(matches(path, p) for p in patterns)

"""`.fleet-review.toml` loading and source-root autodetection."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from fleet_review import globs

CONFIG_NAME = ".fleet-review.toml"

DEFAULT_EXCLUDES = [
    "*_test.go",
    "tests/",
    "test/",
    "test_*.py",
    "*_test.py",
    "conftest.py",
]

SOURCE_SUFFIXES = {".go": "go", ".py": "python"}


class ConfigError(Exception):
    pass


@dataclass
class Config:
    paths: list[str]
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    min_clone_lines: int = 8
    new_function_ccn: int = 15
    min_ccn_delta: int = 3
    autodetected_paths: bool = False

    def language(self, path: str) -> str | None:
        return SOURCE_SUFFIXES.get(Path(path).suffix)

    def in_scope(self, path: str) -> bool:
        """A repo-relative posix path is analysed: known language, under a root, not excluded."""
        if self.language(path) is None:
            return False
        if not any(r in (".", "") or path == r or path.startswith(r + "/") for r in self.paths):
            return False
        return not globs.matches_any(path, self.exclude)


def _norm_path(p: str) -> str:
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    p = p.rstrip("/")
    return p or "."


def detect_paths(root: Path) -> list[str]:
    paths: list[str] = []
    if (root / "go.mod").is_file():
        paths += [d for d in ("cmd", "internal", "pkg") if (root / d).is_dir()]
    if (root / "pyproject.toml").is_file():
        if (root / "src").is_dir():
            paths.append("src")
        else:
            for child in sorted(root.iterdir()):
                if (
                    child.is_dir()
                    and not child.name.startswith(".")
                    and (child / "__init__.py").is_file()
                    and not globs.matches_any(child.name + "/x.py", DEFAULT_EXCLUDES)
                ):
                    paths.append(child.name)
    return paths or ["."]


def _str_list(table: dict, key: str) -> list[str]:
    v = table[key]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{CONFIG_NAME}: `{key}` must be a list of strings")
    return v


def _pos_int(table: dict, key: str) -> int:
    v = table[key]
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise ConfigError(f"{CONFIG_NAME}: `{key}` must be a positive integer")
    return v


def load(root: Path) -> Config:
    table: dict = {}
    cfg_file = root / CONFIG_NAME
    if cfg_file.is_file():
        try:
            table = tomllib.loads(cfg_file.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
            raise ConfigError(f"{CONFIG_NAME}: {e}") from e
    unknown = set(table) - {
        "paths",
        "exclude",
        "min_clone_lines",
        "new_function_ccn",
        "min_ccn_delta",
    }
    if unknown:
        raise ConfigError(f"{CONFIG_NAME}: unknown keys: {', '.join(sorted(unknown))}")

    cfg = Config(paths=[])
    if "paths" in table:
        cfg.paths = [_norm_path(p) for p in _str_list(table, "paths")]
    else:
        cfg.paths = detect_paths(root)
        cfg.autodetected_paths = True
    if "exclude" in table:
        cfg.exclude = DEFAULT_EXCLUDES + _str_list(table, "exclude")
    if "min_clone_lines" in table:
        cfg.min_clone_lines = _pos_int(table, "min_clone_lines")
    if "new_function_ccn" in table:
        cfg.new_function_ccn = _pos_int(table, "new_function_ccn")
    if "min_ccn_delta" in table:
        cfg.min_ccn_delta = _pos_int(table, "min_ccn_delta")
    return cfg

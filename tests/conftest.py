from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fleet_review import cli
from fleet_review.duplication import DEFAULT_JSCPD_VERSION


class Repo:
    """A throwaway git repo with a few helpers."""

    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.path), *args], capture_output=True, text=True, check=True
        )
        return proc.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        f = self.path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")

    def config(self, **values: int) -> None:
        """Write `.fleet-review.toml` with integer settings."""
        self.write(".fleet-review.toml", "".join(f"{k} = {v}\n" for k, v in values.items()))

    def commit(self, msg: str = "c") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run(self, base: str = "main", *extra: str, capsys=None) -> dict:
        """Run fleet-review against this repo and return the parsed review.json."""
        out = self.path.parent / f"{self.path.name}-out"
        out.mkdir(exist_ok=True)
        rc = cli.main(
            [
                "--repo",
                str(self.path),
                "--base",
                base,
                "--json",
                str(out / "review.json"),
                "--report",
                str(out / "report.md"),
                *extra,
            ]
        )
        assert rc == 0
        self.last_report = (out / "report.md").read_text()
        return json.loads((out / "review.json").read_text())


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    path = tmp_path / "repo"
    path.mkdir()
    r = Repo(path)
    r.git("init", "-q", "-b", "main")
    r.git("config", "user.email", "t@example.com")
    r.git("config", "user.name", "T")
    r.git("config", "commit.gpgsign", "false")
    r.write("go.mod", "module example.com/m\n\ngo 1.22\n")
    r.write("internal/keep.go", "package internal\n")
    r.commit("init")
    r.git("checkout", "-q", "-b", "work")
    return r


def findings(result: dict, check: str) -> list[dict]:
    return result["checks"][check]["findings"]


def names(result: dict, check: str = "complexity") -> list[str]:
    return sorted(f["function"] for f in findings(result, check))


def _jscpd_works() -> bool:
    npx = shutil.which("npx")
    if not npx:
        return False
    try:
        proc = subprocess.run(
            [npx, "-y", f"jscpd@{DEFAULT_JSCPD_VERSION}", "--version"],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and DEFAULT_JSCPD_VERSION in proc.stdout


@pytest.fixture(scope="session")
def jscpd_available() -> bool:
    return _jscpd_works()


@pytest.fixture
def need_jscpd(jscpd_available: bool) -> None:
    if not jscpd_available:
        pytest.skip("npx/jscpd is not available")

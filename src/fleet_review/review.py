"""Run the checks over a repo and assemble the result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fleet_review import complexity, config, duplication, gitutil
from fleet_review.model import CheckResult

SCHEMA_VERSION = 1


@dataclass
class Review:
    root: Path
    base_ref: str
    base_sha: str
    merge_base: str
    head_sha: str
    cfg: config.Config
    files_in_scope: int
    results: list[CheckResult]

    def to_json(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "base": {"ref": self.base_ref, "sha": self.base_sha, "merge_base": self.merge_base},
            "head": self.head_sha,
            "changed_files_in_scope": self.files_in_scope,
            "config": {
                "paths": self.cfg.paths,
                "paths_autodetected": self.cfg.autodetected_paths,
                "exclude": self.cfg.exclude,
                "min_clone_lines": self.cfg.min_clone_lines,
                "new_function_ccn": self.cfg.new_function_ccn,
                "min_ccn_delta": self.cfg.min_ccn_delta,
            },
            "checks": {
                r.name: {
                    "status": r.status,
                    **({"reason": r.reason} if r.reason else {}),
                    **({"detail": r.detail} if r.detail else {}),
                    "findings": r.findings,
                }
                for r in self.results
            },
        }


def review(root: Path, base_ref: str, jscpd_version: str, cfg: config.Config) -> Review:
    base_sha = gitutil.resolve_commit(root, base_ref)
    mb = gitutil.merge_base(root, base_sha)
    head = gitutil.resolve_commit(root, "HEAD")
    changes = gitutil.changes_since(root, mb)
    in_scope = [c for c in changes if cfg.in_scope(c.path)]

    def read_base(path: str) -> str | None:
        return gitutil.show(root, mb, path)

    results: list[CheckResult] = []
    for name, run in (
        ("duplication", lambda: duplication.check(cfg, root, changes, jscpd_version)),
        ("complexity", lambda: complexity.check(cfg, root, changes, read_base)),
    ):
        try:
            results.append(run())
        except Exception as e:  # advisory tool: a broken check must not break the others
            results.append(CheckResult.skipped(name, f"internal error: {type(e).__name__}: {e}"))
    return Review(root, base_ref, base_sha, mb, head, cfg, len(in_scope), results)

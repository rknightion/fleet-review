"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fleet_review import __version__, config, gitutil, report
from fleet_review.duplication import DEFAULT_JSCPD_VERSION
from fleet_review.review import review

DEFAULT_REPORT = ".review/report.md"
DEFAULT_JSON = ".review/review.json"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fleet-review",
        description="Advisory report of what a change introduced (duplication, complexity).",
    )
    p.add_argument("--base", default="origin/main", help="base ref (default: origin/main)")
    p.add_argument("--repo", default=".", help="repository path (default: current directory)")
    p.add_argument("--json", dest="json_path", help=f"JSON output path (default: {DEFAULT_JSON})")
    p.add_argument(
        "--report", dest="report_path", help=f"Markdown path (default: {DEFAULT_REPORT})"
    )
    p.add_argument(
        "--jscpd-version",
        default=DEFAULT_JSCPD_VERSION,
        help=f"jscpd version to run via npx (default: {DEFAULT_JSCPD_VERSION})",
    )
    p.add_argument("--version", action="version", version=f"fleet-review {__version__}")
    return p


def _fail(msg: str) -> int:
    print(f"fleet-review: {msg}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = gitutil.toplevel(Path(args.repo))
        cfg = config.load(root)
        rev = review(root, args.base, args.jscpd_version, cfg)
    except (gitutil.GitError, config.ConfigError) as e:
        return _fail(str(e))

    report_path = Path(args.report_path) if args.report_path else root / DEFAULT_REPORT
    json_path = Path(args.json_path) if args.json_path else root / DEFAULT_JSON
    for path, text in (
        (report_path, report.markdown(rev)),
        (json_path, json.dumps(rev.to_json(), indent=2) + "\n"),
    ):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as e:
            return _fail(f"cannot write {path}: {e}")
    print(report.stdout_summary(rev))
    return 0


if __name__ == "__main__":
    sys.exit(main())

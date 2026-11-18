# Review the local change-report tool

## Software and operators

Developers run `fleet-review` to see duplication and complexity changes in Go and Python worktrees.
Trace the CLI through `src/fleet_review/cli.py`, `review.py` and the analysis and report modules.

## Invariants

Keep reports advisory. Measure changes from the merge base through the working tree, including
untracked source that passes the ignore rules. Keep findings tied to changed lines and stable
across unrelated line movement and function signature edits. Preserve the distinction between
import-only clones and clones with executable changes.

## Sensitive changes

Limit repository access to the selected source paths and base. Keep the analyzed worktree intact
and write only the requested reports. Validate configured path and ref handling and preserve the
external analyzer version check and explicit skip reason when it is unavailable.

## Existing and additional checks

Use `just check </dev/null` for Ruff and pytest. Extend the existing temporary repository fixtures
in `tests/` for behavior changes. Verify both affected and unaffected source, and run the actual
duplication tests with the pinned analyzer available when reviewing changes to that path.

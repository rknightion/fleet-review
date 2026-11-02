# fleet-review

An advisory, local report of what a change introduced, for Go and Python repos. It never gates
anything and exits 0 unless it cannot run at all.

Two checks, each reported as `ok`, `attention` or `skipped` (with the reason):

- **duplication**: clones found by [jscpd](https://github.com/kucherenko/jscpd) over the
  configured source roots, kept only when at least one side overlaps a changed line. Reported as
  `new.go:18-32 repeats old.go:41-56 (15 lines)`, changed side first, grouped into "within this
  change" and "repeats existing code".
- **complexity**: [lizard](https://github.com/terryyin/lizard) on the base and head versions of
  every changed file. Reports (a) existing functions whose cyclomatic complexity (CCN) rose and
  (b) new functions with CCN above `new_function_ccn`.

## Run

From inside the repo you want reviewed:

```sh
uvx --from git+https://github.com/rknightion/fleet-review@<sha> fleet-review --base origin/main
```

```
fleet-review [--base REF] [--repo PATH] [--json PATH] [--report PATH] [--jscpd-version V]
```

| Flag | Default | |
|---|---|---|
| `--base` | `origin/main` | Ref the change is measured against. |
| `--repo` | `.` | Repository to review (its top level is used). |
| `--json` | `.review/review.json` | Machine-readable result. |
| `--report` | `.review/report.md` | Markdown report. |
| `--jscpd-version` | `5.4.2` | jscpd release run through `npx -y jscpd@<version>`. |

Stdout is one line per check. Exit status is 0, or 2 for bad arguments, a path that is not a git
repository, a base ref that does not exist, or an invalid `.fleet-review.toml`.

Add `.review/` to the consuming repo's `.gitignore`.

### What counts as "changed"

The diff is `git merge-base <base> HEAD` against the **working tree**, plus untracked,
non-ignored files treated as fully added. Using the merge base means a branch that is behind its
base is not blamed for the base's own commits. Base-side file contents are read with
`git show`; the tool never checks out, stashes, fetches or writes to the repository (it only
writes its two output files).

### External tools

- `jscpd` runs as `npx -y jscpd@<version>`. A `jscpd` on `PATH` is used only if its `--version`
  equals the pin. If neither is usable the duplication check is `skipped` with the reason and
  complexity still runs. jscpd 5.x has no `--threads` flag; the equivalent `--workers 1` is
  always passed. `--min-tokens` is set to `3 x min_clone_lines`, because jscpd would otherwise
  silently apply its own floor of 50 tokens.
- `lizard==1.25.0` is a regular dependency.

### Function identity

Findings are matched between base and head by file and function name **without the parameter
list**, so a signature change is not a delete plus an add. Go methods carry their receiver type
(`(T) Name` and `(U) Name` in one file are `T.Name` and `U.Name`); Python methods carry their class
(`A.run`). Go closures and other anonymous functions are folded into their enclosing named
function by line range (their extra complexity counts towards it), and are never reported under
lizard's positional names. Repeated names in one file (Go `init`, Python property setters) are
told apart by order (`init#2`).

Finding ids in `review.json` are a hash of the check, the file, and the function name (for clones,
the partner file and function too). They never include line numbers, so they survive unrelated
edits above a finding.

## Config

Optional `.fleet-review.toml` at the repo root:

```toml
paths = ["cmd", "internal"]   # source roots
exclude = ["internal/gen/"]   # extra globs, added to the default test excludes
min_clone_lines = 8
new_function_ccn = 15
min_ccn_delta = 3
```

| Key | Default | |
|---|---|---|
| `paths` | autodetect | Source roots, relative to the repo root. Autodetect: `go.mod` gives whichever of `cmd`, `internal`, `pkg` exist; `pyproject.toml` gives `src` if it exists, otherwise top-level directories containing `__init__.py`. Anything else falls back to `.`. |
| `exclude` | (none) | Extra globs, added to the built-in test excludes. `name/` matches a directory anywhere, a glob with no `/` matches the file name, anything else is matched against the repo-relative path (`**` supported). |
| `min_clone_lines` | `8` | Smallest clone, in lines, to report. |
| `new_function_ccn` | `15` | A new function is reported when its CCN is above this. |
| `min_ccn_delta` | `3` | An existing function is reported as grown only when its CCN rose by at least this much (so `1` reports every increase). Does not affect new functions. |

Tests are excluded by default: `*_test.go`, `tests/`, `test/`, `test_*.py`, `*_test.py`,
`conftest.py`.

## Noise filters

- **Small growth.** An existing function whose CCN rose by less than `min_ccn_delta` is not
  reported. New functions over `new_function_ccn` are unaffected.
- **Import-only clones.** A clone is dropped when every non-blank changed line it overlaps (on
  each side that was changed) is an import line. Go: an `import` declaration or any line inside
  an `import ( ... )` block (line-based). Python (via `ast`): `import` and `from ... import`
  statements, multi-line parenthesised ones included, and an `if TYPE_CHECKING:` (or
  `typing.TYPE_CHECKING`) block whose body is only imports. A clone that also overlaps a changed
  non-import line is kept. A changed blank line alone does not count as an import line, so a
  clone whose only changed lines are blank is kept. The count dropped is shown in the check's
  detail.

## Limits

- A clone is reported when one side overlaps a changed line, so touching a non-import line
  inside an existing clone reports that clone.
- Functions moved between files look new; functions renamed look new.
- Only `.go` and `.py` files are analysed.

## Develop

```sh
just setup   # uv sync
just check   # fmt-check, lint, test
```

The tests build throwaway git repos and use real lizard. The duplication tests need `npx` and are
skipped when it is not available.

## Licence

MIT, see `LICENSE`.

from __future__ import annotations

import pytest

from conftest import findings
from gosrc import clone_func, go_file

IMPORTS = 'import "fmt"\n'

pytestmark = pytest.mark.usefixtures("need_jscpd")


def _dups(result: dict) -> list[dict]:
    return findings(result, "duplication")


def _base_with_old(repo) -> None:
    repo.git("checkout", "-q", "main")
    repo.write("internal/old.go", go_file(clone_func("Old"), imports=IMPORTS))
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")


def test_new_clone_across_two_files(repo):
    _base_with_old(repo)
    repo.write("internal/new.go", go_file(clone_func("Fresh"), imports=IMPORTS))
    result = repo.run()
    [d] = _dups(result)
    assert d["group"] == "repeats_existing"
    assert (d["file"], d["function"]) == ("internal/new.go", "Fresh")
    assert (d["partner"]["file"], d["partner"]["function"]) == ("internal/old.go", "Old")
    # Changed side first, with a line range and a size.
    assert d["message"].startswith("internal/new.go:")
    assert " repeats internal/old.go:" in d["message"]
    assert d["message"].endswith(" lines)")
    assert "### Repeats existing code" in repo.last_report
    assert result["checks"]["duplication"]["status"] == "attention"


def test_changed_side_is_listed_first_whatever_jscpd_orders(repo):
    # `aaa.go` sorts before `zzz.go`, so jscpd lists the unchanged file first here.
    repo.git("checkout", "-q", "main")
    repo.write("internal/aaa.go", go_file(clone_func("Old"), imports=IMPORTS))
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("internal/zzz.go", go_file(clone_func("Fresh"), imports=IMPORTS))
    [d] = _dups(repo.run())
    assert d["file"] == "internal/zzz.go"
    assert d["partner"]["file"] == "internal/aaa.go"


def test_clone_within_the_change(repo):
    repo.write("internal/one.go", go_file(clone_func("One"), imports=IMPORTS))
    repo.write("internal/two.go", go_file(clone_func("Two"), imports=IMPORTS))
    result = repo.run()
    [d] = _dups(result)
    assert d["group"] == "within_change"
    assert {d["file"], d["partner"]["file"]} == {"internal/one.go", "internal/two.go"}
    assert "### Within this change" in repo.last_report


def test_untracked_file_is_analysed(repo):
    _base_with_old(repo)
    repo.write("internal/untracked.go", go_file(clone_func("Fresh"), imports=IMPORTS))
    assert repo.git("status", "--porcelain").count("??") == 1
    [d] = _dups(repo.run())
    assert d["file"] == "internal/untracked.go"


def test_unchanged_existing_clones_are_not_reported(repo):
    repo.git("checkout", "-q", "main")
    repo.write("internal/one.go", go_file(clone_func("One"), imports=IMPORTS))
    repo.write("internal/two.go", go_file(clone_func("Two"), imports=IMPORTS))
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("internal/other.go", "package internal\n\nfunc Other() {}\n")
    assert _dups(repo.run()) == []


def test_ids_ignore_line_numbers(repo):
    _base_with_old(repo)
    repo.write("internal/new.go", go_file(clone_func("Fresh"), imports=IMPORTS))
    first = _dups(repo.run())[0]
    repo.write("internal/new.go", go_file("// pad\n// pad\n", clone_func("Fresh"), imports=IMPORTS))
    second = _dups(repo.run())[0]
    assert second["start"] != first["start"]
    assert second["id"] == first["id"]


def test_min_clone_lines_is_configurable(repo):
    _base_with_old(repo)
    repo.write(".fleet-review.toml", "min_clone_lines = 40\n")
    repo.write("internal/new.go", go_file(clone_func("Fresh"), imports=IMPORTS))
    assert _dups(repo.run()) == []


def test_python_clone(repo):
    # pytest names the checkout dir `test_python_clone0`: it must not trip the `test_*.py` exclude.
    repo.git("checkout", "-q", "main")
    repo.write("pyproject.toml", "[project]\nname='x'\n")
    body = (
        "def {n}(items):\n    total = 0\n    for i, it in enumerate(items):\n"
        "        if not it:\n            continue\n        total += len(it) * i\n"
        "        print('item', it, total)\n    if total > 10:\n        return total - 10\n"
        "    return total\n"
    )
    repo.write("src/pkg/old.py", body.format(n="old"))
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("src/pkg/new.py", body.format(n="fresh"))
    [d] = _dups(repo.run())
    assert (d["file"], d["function"]) == ("src/pkg/new.py", "fresh")

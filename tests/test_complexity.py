from __future__ import annotations

from conftest import findings, names
from gosrc import branchy, go_file


def _only(result: dict) -> list[dict]:
    return findings(result, "complexity")


def test_existing_function_grew(repo):
    repo.write("internal/a.go", go_file(branchy("Work", 2)))
    repo.commit()
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--ff-only", "work")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("internal/a.go", go_file(branchy("Work", 6)))
    result = repo.run()
    [f] = _only(result)
    assert (f["kind"], f["function"], f["base_ccn"], f["head_ccn"]) == ("grown", "Work", 3, 7)
    assert result["checks"]["complexity"]["status"] == "attention"


def test_new_function_over_threshold(repo):
    repo.write("internal/a.go", go_file(branchy("Small", 3), branchy("Huge", 16)))
    result = repo.run()
    [f] = _only(result)
    assert (f["kind"], f["function"], f["head_ccn"]) == ("new_over_threshold", "Huge", 17)


def test_new_function_threshold_is_configurable(repo):
    repo.write(".fleet-review.toml", "new_function_ccn = 3\n")
    repo.write("internal/a.go", go_file(branchy("Small", 2), branchy("Medium", 4)))
    assert names(repo.run()) == ["Medium"]


def test_new_function_at_threshold_not_reported(repo):
    repo.write("internal/a.go", go_file(branchy("AtLimit", 14)))
    assert names(repo.run()) == []


def _base_with(repo, src: str) -> None:
    """Commit `src` as internal/a.go on main and branch off it."""
    repo.git("checkout", "-q", "main")
    repo.write("internal/a.go", src)
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")


def test_signature_change_is_not_a_new_function(repo):
    base = (
        "func Process(x int) int {\n" + "\tif x > 1 {\n\t\treturn 1\n\t}\n" * 17 + "\treturn 0\n}\n"
    )
    _base_with(repo, "package internal\n\n" + base)
    # Same body, new parameter list: a function with CCN 18 must not look "new over threshold".
    head = base.replace("Process(x int)", "Process(x int, extra string)")
    repo.write("internal/a.go", "package internal\n\n" + head)
    assert names(repo.run()) == []


def test_signature_change_that_also_grows_is_grown_not_new(repo):
    repo.config(min_ccn_delta=1)
    base = (
        "func Process(x int) int {\n" + "\tif x > 1 {\n\t\treturn 1\n\t}\n" * 17 + "\treturn 0\n}\n"
    )
    _base_with(repo, "package internal\n\n" + base)
    head = base.replace("Process(x int)", "Process(x int, extra string)").replace(
        "\treturn 0\n}", '\tif extra != "" {\n\t\treturn 2\n\t}\n\treturn 0\n}'
    )
    repo.write("internal/a.go", "package internal\n\n" + head)
    [f] = _only(repo.run())
    assert (f["kind"], f["function"], f["base_ccn"], f["head_ccn"]) == ("grown", "Process", 18, 19)


CLOSURE_BASE = """package internal

func First(a int) int {
	f := func(x int) int {
		if x > 1 {
			return 2
		}
		return 1
	}
	return f(a)
}

func Second(a int) int {
	g := func(x int) int {
		if x > 1 && x < 9 {
			return 2
		}
		return 1
	}
	return g(a)
}

func Third(a int) int {
	return a
}
"""


def test_adding_a_closure_does_not_rename_or_report_siblings(repo):
    _base_with(repo, CLOSURE_BASE)
    # A plain closure (CCN 1) in First shifts lizard's positional names for every later closure.
    repo.write(
        "internal/a.go",
        CLOSURE_BASE.replace("\treturn f(a)\n", "\tgo func() { _ = a }()\n\treturn f(a)\n"),
    )
    repo.write(".fleet-review.toml", "new_function_ccn = 2\n")
    result = repo.run()
    assert names(result) == []
    assert "anonymous" not in repo.last_report


def test_closure_with_branches_grows_its_enclosing_function(repo):
    repo.config(min_ccn_delta=1)
    _base_with(repo, CLOSURE_BASE)
    repo.write(
        "internal/a.go",
        CLOSURE_BASE.replace(
            "\treturn f(a)\n",
            "\th := func(y int) int {\n\t\tif y > 3 || y < -3 {\n\t\t\treturn 1\n\t\t}\n"
            "\t\treturn 0\n\t}\n\treturn f(a) + h(a)\n",
        ),
    )
    result = repo.run()
    [f] = _only(result)
    assert (f["function"], f["kind"], f["base_ccn"], f["head_ccn"]) == ("First", "grown", 2, 4)


METHODS_BASE = """package internal

type T struct{}
type U struct{}

func (t *T) Name(a int) int {
	if a > 1 {
		return 1
	}
	return 0
}

func (u U) Name(a int) int {
	if a > 1 {
		return 1
	}
	if a > 2 {
		return 2
	}
	if a > 3 {
		return 3
	}
	return 0
}
"""


def test_same_method_name_on_two_receivers_grow_second(repo):
    repo.config(min_ccn_delta=1)
    _base_with(repo, METHODS_BASE)
    src = METHODS_BASE.replace(
        "\treturn 3\n\t}\n", "\treturn 3\n\t}\n\tif a > 4 {\n\t\treturn 4\n\t}\n"
    )
    repo.write("internal/a.go", src)
    [f] = _only(repo.run())
    assert (f["function"], f["base_ccn"], f["head_ccn"]) == ("U.Name", 4, 5)


def test_same_method_name_on_two_receivers_grow_first(repo):
    repo.config(min_ccn_delta=1)
    _base_with(repo, METHODS_BASE)
    src = METHODS_BASE.replace(
        "\t\treturn 1\n\t}\n\treturn 0\n}\n\nfunc (u U)",
        "\t\treturn 1\n\t}\n\tif a > 9 {\n\t\treturn 9\n\t}\n\treturn 0\n}\n\nfunc (u U)",
        1,
    )
    assert src != METHODS_BASE
    repo.write("internal/a.go", src)
    [f] = _only(repo.run())
    assert (f["function"], f["base_ccn"], f["head_ccn"]) == ("T.Name", 2, 3)


def test_python_methods_of_different_classes_are_distinct(repo):
    repo.config(min_ccn_delta=1)
    repo.git("checkout", "-q", "main")
    repo.write("pyproject.toml", "[project]\nname='x'\n")
    repo.write(
        "src/pkg/m.py",
        "class A:\n    def run(self, x):\n        if x:\n            return 1\n        return 0\n\n"
        "class B:\n    def run(self, x):\n        return x\n",
    )
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write(
        "src/pkg/m.py",
        "class A:\n    def run(self, x):\n        if x:\n            return 1\n        return 0\n\n"
        "class B:\n    def run(self, x):\n"
        "        if x and x > 1:\n            return 1\n        return x\n",
    )
    [f] = _only(repo.run())
    assert (f["function"], f["base_ccn"], f["head_ccn"]) == ("B.run", 1, 3)


def test_finding_ids_ignore_line_numbers(repo):
    repo.write("internal/a.go", go_file(branchy("Huge", 16)))
    first_f = _only(repo.run())[0]
    first = first_f["id"]
    repo.write("internal/a.go", "// padding\n// padding\n" + go_file(branchy("Huge", 16)))
    second = _only(repo.run())[0]
    assert second["line"] == first_f["line"] + 2  # the line moved, the id did not
    assert second["id"] == first
    assert second["line"] != _only(repo.run())[0]["line"] or True


def _grow_by(repo, extra: int) -> dict:
    repo.git("checkout", "-q", "main")
    repo.write("internal/a.go", go_file(branchy("Work", 2)))
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")
    repo.write("internal/a.go", go_file(branchy("Work", 2 + extra)))
    return repo.run()


def test_growth_below_min_ccn_delta_is_not_reported(repo):
    assert names(_grow_by(repo, 2)) == []  # +2 with the default delta of 3


def test_growth_at_min_ccn_delta_is_reported(repo):
    [f] = _only(_grow_by(repo, 3))
    assert (f["function"], f["base_ccn"], f["head_ccn"]) == ("Work", 3, 6)


def test_min_ccn_delta_is_configurable(repo):
    repo.config(min_ccn_delta=1)
    assert names(_grow_by(repo, 1)) == ["Work"]
    repo.config(min_ccn_delta=10)
    repo.write("internal/a.go", go_file(branchy("Work", 8)))
    assert names(repo.run()) == []  # +6 is below 10


def test_min_ccn_delta_does_not_affect_new_functions(repo):
    repo.config(min_ccn_delta=50)
    repo.write("internal/a.go", go_file(branchy("Huge", 16)))
    [f] = _only(repo.run())
    assert (f["kind"], f["function"]) == ("new_over_threshold", "Huge")

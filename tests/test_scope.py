from __future__ import annotations

from conftest import findings, names
from fleet_review import cli, complexity, config, duplication, globs
from gosrc import branchy, clone_func, go_file


def test_base_only_commits_are_not_reported_as_reverted(repo):
    """A branch that is behind its base is compared from the merge base, not the base tip."""
    repo.git("checkout", "-q", "main")
    repo.write("internal/a.go", go_file(branchy("Work", 9), branchy("Stable", 1)))
    repo.commit("shared")
    repo.git("checkout", "-q", "-b", "stale")  # stays at the shared commit
    repo.git("checkout", "-q", "main")
    # Base-only: simplifies Work and adds a file.
    repo.write("internal/a.go", go_file(branchy("Work", 1), branchy("Stable", 1)))
    repo.write("internal/base_only.go", go_file(clone_func("BaseOnly"), imports='import "fmt"\n'))
    repo.commit("base-only")
    repo.git("checkout", "-q", "stale")
    repo.write("internal/mine.go", "package internal\n\nfunc Mine() int {\n\treturn 1\n}\n")
    result = repo.run(base="main")
    # Naively diffing against main's tip would report Work as having grown from 2 to 10.
    assert names(result) == []
    assert result["changed_files_in_scope"] == 1
    assert result["base"]["merge_base"] != result["base"]["sha"]
    assert findings(result, "duplication") == []


def test_tests_are_excluded_by_default(repo):
    repo.write("internal/a_test.go", go_file(branchy("TestHuge", 30)))
    repo.write("internal/tests/helper.go", go_file(branchy("Helper", 30)))
    repo.write("internal/test/helper.go", go_file(branchy("Helper2", 30)))
    repo.write("src/pkg/test_thing.py", "def f(x):\n" + "    if x:\n        pass\n" * 30)
    repo.write("src/pkg/thing_test.py", "def f(x):\n" + "    if x:\n        pass\n" * 30)
    repo.write("src/pkg/conftest.py", "def f(x):\n" + "    if x:\n        pass\n" * 30)
    repo.write("internal/real.go", go_file(branchy("Real", 30)))
    result = repo.run()
    assert names(result) == ["Real"]
    assert result["changed_files_in_scope"] == 1


def test_user_exclude_adds_to_the_defaults(repo):
    repo.write(".fleet-review.toml", 'exclude = ["internal/gen/"]\n')
    repo.write("internal/gen/big.go", go_file(branchy("Gen", 30)))
    repo.write("internal/real.go", go_file(branchy("Real", 30)))
    repo.write("internal/x_test.go", go_file(branchy("T", 30)))
    assert names(repo.run()) == ["Real"]


def test_files_outside_the_source_roots_are_ignored(repo):
    repo.write("scripts/tool.go", go_file(branchy("Tool", 30)))
    repo.write("internal/real.go", go_file(branchy("Real", 30)))
    assert names(repo.run()) == ["Real"]


def test_jscpd_unavailable_skips_duplication_only(repo, monkeypatch):
    monkeypatch.setattr(duplication.shutil, "which", lambda _name: None)
    repo.write("internal/real.go", go_file(branchy("Real", 30)))
    result = repo.run()
    dup = result["checks"]["duplication"]
    assert dup["status"] == "skipped"
    assert "jscpd" in dup["reason"]
    assert dup["findings"] == []
    assert names(result) == ["Real"]
    assert "## Duplication: skipped" in repo.last_report


def test_jscpd_failure_skips_duplication(repo, monkeypatch):
    monkeypatch.setattr(duplication, "resolve_jscpd", lambda _v: (["false"], ""))
    repo.write("internal/real.go", go_file(branchy("Real", 30)))
    result = repo.run()
    assert result["checks"]["duplication"]["status"] == "skipped"
    assert "jscpd failed" in result["checks"]["duplication"]["reason"]
    assert names(result) == ["Real"]


def test_path_jscpd_is_used_only_when_version_matches(tmp_path, monkeypatch):
    fake = tmp_path / "jscpd"
    fake.write_text("#!/bin/sh\necho 'jscpd 4.0.5'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    real_which = duplication.shutil.which

    def which(name, *a, **kw):
        return real_which(name, path=f"{tmp_path}:/usr/bin:/bin") if name == "jscpd" else "/x/npx"

    monkeypatch.setattr(duplication.shutil, "which", which)
    cmd, _ = duplication.resolve_jscpd("5.4.2")
    assert cmd == ["/x/npx", "-y", "jscpd@5.4.2"]
    fake.write_text("#!/bin/sh\necho 'jscpd 5.4.2'\n")
    cmd, _ = duplication.resolve_jscpd("5.4.2")
    assert cmd == [str(fake)]


def test_exit_codes(tmp_path, repo):
    assert cli.main(["--repo", str(tmp_path / "nope")]) == 2
    plain = tmp_path / "plain"
    plain.mkdir()
    assert cli.main(["--repo", str(plain)]) == 2
    assert cli.main(["--repo", str(repo.path), "--base", "no-such-ref"]) == 2
    out = tmp_path / "o"
    assert (
        cli.main(
            [
                "--repo",
                str(repo.path),
                "--base",
                "main",
                "--report",
                str(out / "r.md"),
                "--json",
                str(out / "j.json"),
            ]
        )
        == 0
    )


def test_bad_arguments_exit_2():
    import pytest

    with pytest.raises(SystemExit) as e:
        cli.main(["--no-such-flag"])
    assert e.value.code == 2


def test_default_outputs_and_no_repo_writes_beyond_review_dir(repo):
    assert cli.main(["--repo", str(repo.path), "--base", "main"]) == 0
    assert (repo.path / ".review/report.md").is_file()
    assert (repo.path / ".review/review.json").is_file()
    assert repo.git("status", "--porcelain").strip() == "?? .review/"
    assert repo.git("stash", "list") == ""


# unit tests -------------------------------------------------------------------------


def test_go_receiver_parsing():
    r = complexity.go_receiver
    assert r("(t*T)Name a int") == "T"
    assert r("(u U)Name") == "U"
    assert r("(g*Gen[K,V])Do x T") == "Gen"
    assert r("(g Gen[K, V])Do x T") == "Gen"
    assert r("(*T)Name") == "T"
    assert r("(T)Name") == "T"
    assert r("Free k K") == ""


def test_glob_matching():
    m = globs.matches
    assert m("a/b/x_test.go", "*_test.go")
    assert m("a/tests/x.py", "tests/")
    assert not m("a/attests/x.py", "tests/")
    assert m("pkg/test_x.py", "test_*.py")
    assert m("conftest.py", "conftest.py")
    assert m("internal/gen/x.go", "internal/gen")
    assert m("internal/gen/x.go", "internal/gen/")
    assert m("internal/a/b/x.go", "internal/**/x.go")
    assert not m("other/gen/x.go", "internal/gen/")
    assert not m("internal/real.go", "*_test.go")


def test_autodetect_paths(tmp_path):
    (tmp_path / "go.mod").write_text("module m\n")
    for d in ("cmd", "internal", "api"):
        (tmp_path / d).mkdir()
    assert config.detect_paths(tmp_path) == ["cmd", "internal"]
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert config.detect_paths(tmp_path) == ["cmd", "internal"]
    (tmp_path / "src").mkdir()
    assert config.detect_paths(tmp_path) == ["cmd", "internal", "src"]

    py = tmp_path / "py"
    py.mkdir()
    (py / "pyproject.toml").write_text("[project]\nname='x'\n")
    (py / "mypkg").mkdir()
    (py / "mypkg" / "__init__.py").write_text("")
    (py / "tests").mkdir()
    (py / "tests" / "__init__.py").write_text("")
    (py / "docs").mkdir()
    assert config.detect_paths(py) == ["mypkg"]


def test_config_validation(tmp_path):
    import pytest

    (tmp_path / ".fleet-review.toml").write_text('min_clone_lines = "x"\n')
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)
    (tmp_path / ".fleet-review.toml").write_text("bogus = 1\n")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)
    (tmp_path / ".fleet-review.toml").write_text('paths = ["./a/", "b"]\nmin_clone_lines = 5\n')
    c = config.load(tmp_path)
    assert (c.paths, c.min_clone_lines, c.new_function_ccn, c.min_ccn_delta) == (
        ["a", "b"],
        5,
        15,
        3,
    )
    (tmp_path / ".fleet-review.toml").write_text("min_ccn_delta = 0\n")
    with pytest.raises(config.ConfigError):
        config.load(tmp_path)
    (tmp_path / ".fleet-review.toml").write_text("min_ccn_delta = 2\n")
    assert config.load(tmp_path).min_ccn_delta == 2

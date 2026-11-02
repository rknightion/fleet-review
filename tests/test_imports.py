from __future__ import annotations

import pytest

from conftest import findings
from fleet_review.imports import import_lines


def test_go_single_import():
    src = 'package p\n\nimport "fmt"\nimport str "strings"\n\nfunc F() {}\n'
    assert import_lines("a.go", src) == {3, 4}


def test_go_import_block_covers_every_line_in_it():
    src = (
        'package p\n\nimport (\n\t"fmt"\n\n\t// network\n\t"net/http"\n\tlog "x/log"\n)\n\n'
        "var x = 1\n"
    )
    assert import_lines("a.go", src) == {3, 4, 5, 6, 7, 8, 9}


def test_go_two_blocks_and_paren_in_string_do_not_leak():
    src = 'package p\n\nimport (\n\t"a"\n)\n\nimport (\n\t"b"\n)\n\nvar s = "import ("\nvar t = 2\n'
    assert import_lines("a.go", src) == {3, 4, 5, 7, 8, 9}


def test_go_non_import_code_is_not_import_lines():
    assert import_lines("a.go", "package p\n\nfunc F() {\n\timportant := 1\n}\n") == set()


def test_python_import_forms():
    src = (
        "import os\nfrom a import b\nfrom c import (\n    d,\n    e,\n)\n\n"
        "def f():\n    import json\n    return json\n\nx = 1\n"
    )
    assert import_lines("a.py", src) == {1, 2, 3, 4, 5, 6, 9}


def test_python_type_checking_block_of_only_imports():
    src = (
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from m import A\n\n"
        "    from n import B\n\nx = 1\n"
    )
    # The `if` line, the blank line inside the block and both imports.
    assert import_lines("a.py", src) == {1, 3, 4, 5, 6}


def test_python_typing_dot_type_checking_block():
    src = "import typing\n\nif typing.TYPE_CHECKING:\n    import m\n"
    assert import_lines("a.py", src) == {1, 3, 4}


def test_python_type_checking_block_with_other_code_keeps_only_the_imports():
    src = "if TYPE_CHECKING:\n    from m import A\n    X = 1\n"
    assert import_lines("a.py", src) == {2}


def test_python_syntax_error_yields_no_import_lines():
    assert import_lines("a.py", "def (:\nimport os\n") == set()


def test_other_languages_have_none():
    assert import_lines("a.txt", "import x\n") == set()


# integration -------------------------------------------------------------------------

HEADER = (
    "import os\nimport sys\nimport json\nimport logging\nimport pathlib\n"
    "from collections import OrderedDict\nfrom dataclasses import dataclass\n"
    "from typing import Any\n{extra}\nlog = logging.getLogger(__name__)\n"
)


def _py_repo(repo, extra: str = "") -> None:
    repo.git("checkout", "-q", "main")
    repo.write("pyproject.toml", "[project]\nname='x'\n")
    repo.write("src/pkg/a.py", HEADER.format(extra=extra) + "\n\ndef a():\n    return 1\n")
    repo.write("src/pkg/b.py", HEADER.format(extra=extra) + "\n\ndef b():\n    return 2\n")
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feature")


@pytest.mark.usefixtures("need_jscpd")
def test_clone_whose_changed_lines_are_only_imports_is_dropped(repo):
    _py_repo(repo)
    # Both headers still match after the same import is added to each.
    for f, fn in (("a", "a"), ("b", "b")):
        text = HEADER.format(extra="import re") + f"\n\ndef {fn}():\n    return 1\n"
        repo.write(f"src/pkg/{f}.py", text)
    result = repo.run()
    assert findings(result, "duplication") == []


@pytest.mark.usefixtures("need_jscpd")
def test_clone_with_a_changed_non_import_line_is_kept(repo):
    _py_repo(repo)
    # Change the `log = ...` line (inside the cloned header) in both files, identically.
    for f, fn in (("a", "a"), ("b", "b")):
        text = (
            HEADER.format(extra="").replace("__name__", "'x'") + f"\n\ndef {fn}():\n    return 1\n"
        )
        repo.write(f"src/pkg/{f}.py", text)
    [d] = findings(repo.run(), "duplication")
    assert d["group"] == "within_change"


@pytest.mark.usefixtures("need_jscpd")
def test_clone_spanning_imports_and_changed_function_code_is_kept(repo):
    _py_repo(repo)
    body = (
        "\n\ndef work(items):\n    total = 0\n    for i, it in enumerate(items):\n"
        "        if not it:\n            continue\n        total += len(it) * i\n"
        "        print('item', it, total)\n    if total > 10:\n        return total - 10\n"
        "    return total\n"
    )
    repo.write("src/pkg/a.py", HEADER.format(extra="import re") + body)
    repo.write("src/pkg/c.py", HEADER.format(extra="import re") + body.replace("work", "other"))
    result = repo.run()
    dups = findings(result, "duplication")
    assert dups, "the function body clone must survive"
    assert any(d["end"] >= 15 for d in dups)

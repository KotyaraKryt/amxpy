from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from amxpy.compiler import check_file, plugin_root
from amxpy.compiler.lint import Flake8Checker

from .conftest import EXAMPLES, MakePlugin

SHOP = """
    from amxpy import Plugin

    from .perks import router

    plugin = Plugin("Shop")
    plugin.include(router)
"""

PERKS = """
    import time

    from amxpy import Router, events

    router = Router()


    @router.on(events.TakeDamage)
    def dmg(e: events.TakeDamage) -> None:
        e.damage = e.dmg * 2
        time.sleep(1)
"""


def _line(path: Path, text: str) -> int:
    return next(n for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if text in line)


def test_examples_are_clean() -> None:
    for file in [*sorted(EXAMPLES.glob("*.py")), *sorted((EXAMPLES / "vip").glob("*.py"))]:
        assert check_file(file) == [], file


def test_plugin_root(make_plugin: MakePlugin) -> None:
    package = make_plugin("shop", SHOP, files={"perks.py": PERKS, "sub/__init__.py": "", "sub/deep.py": ""})
    assert plugin_root(package / "sub" / "deep.py") == package.resolve()
    assert plugin_root(package / "__init__.py") == package.resolve()
    single = make_plugin("solo", "x = 1")
    assert plugin_root(single) == single.resolve()


def test_package_module_gets_only_its_diagnostics(make_plugin: MakePlugin) -> None:
    package = make_plugin("shop", SHOP, files={"perks.py": PERKS})
    perks = package / "perks.py"
    found = check_file(perks)
    assert [(d.code, d.line) for d in found] == [("AMX101", _line(perks, "e.dmg")), ("AMX103", _line(perks, "sleep(1)"))]
    assert {Path(d.file) for d in found} == {perks.resolve()}
    assert [d.severity for d in found] == ["error", "warning"]
    assert check_file(package / "__init__.py") == []


def test_unsaved_text_wins_over_disk(make_plugin: MakePlugin) -> None:
    package = make_plugin("shop", SHOP, files={"perks.py": PERKS})
    fixed = (package / "perks.py").read_text(encoding="utf-8").replace("e.dmg", "e.damage")
    assert [d.code for d in check_file(package / "perks.py", fixed)] == ["AMX103"]


def test_module_without_amxpy_import_is_checked_with_its_plugin(make_plugin: MakePlugin) -> None:
    package = make_plugin("shop", SHOP, files={"perks.py": "from amxpy import Router\nrouter = Router()\n",
                                                "data.py": "TEXT = open('motd.txt').read()\n"})
    assert [d.code for d in check_file(package / "data.py")] == ["AMX301"]


def test_code_without_plugin_is_ignored(tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    helper.write_text("from amxpy import events\n\n\ndef damage(e: events.TakeDamage) -> float:\n    return e.dmg\n")
    other = tmp_path / "other.py"
    other.write_text("import time\ntime.sleep(1)\n")
    assert check_file(helper) == []
    assert check_file(other) == []


def test_flake8_checker(make_plugin: MakePlugin) -> None:
    package = make_plugin("shop", SHOP, files={"perks.py": PERKS})
    perks = package / "perks.py"
    lines = perks.read_text(encoding="utf-8").splitlines(keepends=True)
    found = list(Flake8Checker(ast.parse("".join(lines)), str(perks), lines).run())
    assert [message.split()[0] for _, _, message, _ in found] == ["AMX101", "AMX103"]
    row, col, message, kind = found[0]
    assert kind is Flake8Checker
    assert col == lines[row - 1].index("e.dmg")  # flake8 ждёт столбец с нуля
    assert message == "AMX101 у TakeDamage нет поля 'dmg' — может быть, damage?"
    assert list(Flake8Checker(ast.parse(""), "stdin", lines).run()) == []


def test_flake8_runs_the_plugin(make_plugin: MakePlugin) -> None:
    pytest.importorskip("flake8")
    package = make_plugin("shop", SHOP, files={"perks.py": PERKS})
    run = subprocess.run(
        [sys.executable, "-m", "flake8", "--select=AMX", str(package)], capture_output=True, text=True, check=False
    )
    assert "AMX101 у TakeDamage нет поля 'dmg'" in run.stdout, run.stdout + run.stderr
    assert "AMX103 time.sleep()" in run.stdout


def test_vscode_extension_knows_all_events() -> None:
    from amxpy.events import CATALOG

    source = (Path(__file__).resolve().parents[1] / "editors" / "vscode" / "completions.js").read_text(encoding="utf-8")
    listed = set(re.findall(r"'(\w+)'", source[source.index("const EVENTS") : source.index("];", source.index("const EVENTS"))]))
    assert listed == set(CATALOG)

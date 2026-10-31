from __future__ import annotations

from pathlib import Path

import pytest

from amxpy.cli import main
from amxpy.compiler import compile_plugin
from amxpy.package import PackageError, read_package, write_package

from .conftest import EXAMPLES, MakePlugin


@pytest.mark.parametrize("source", ["hello.py", "ui_demo.py", "no_awp.py", "round_mvp.py", "welcome_back.py", "vip"])
def test_examples_compile_cleanly(source: str) -> None:
    result = compile_plugin(EXAMPLES / source)
    assert result.ok
    assert result.diagnostics == []


def test_vip_manifest_and_include() -> None:
    result = compile_plugin(EXAMPLES / "vip")
    manifest = result.require().manifest
    assert manifest["name"] == "vip" and manifest["title"] == "VIP" and manifest["version"] == "1.2.0"
    assert {"event": "PlayerSpawn", "post": True} in manifest["events"]
    assert manifest["commands"][1]["usage"] == "amx_vip_add <target> [days]"
    assert [n["name"] for n in manifest["natives"]] == ["vip_is_user_vip", "vip_days_left"]
    assert manifest["forwards"] == [{"name": "vip_granted", "params": [["player", "p"], ["days", "i"]]}]
    assert sorted(result.require().data) == ["lang/en.toml", "lang/ru.toml"]
    assert result.include is not None
    assert "native bool:vip_is_user_vip(player);" in result.include
    assert "forward vip_granted(player, days);" in result.include
    assert "#pragma reqlib vip" in result.include


def test_include_renders_tags_defaults_and_string_results(make_plugin: MakePlugin) -> None:
    result = compile_plugin(make_plugin("tags", '''
        from amxpy import Player, Plugin
        plugin = Plugin("Tags")

        @plugin.native
        def tags_mix(player: Player, speed: float = 1.5, flag: bool = True, note: str = "a\\"b") -> float:
            return speed

        @plugin.native
        def tags_name(player: Player) -> str:
            return ""
    '''))
    assert result.include is not None
    assert 'native Float:tags_mix(player, Float:speed = 1.5, bool:flag = true, const note[] = "a^"b");' in result.include
    assert "native tags_name(player, output[], maxlen);" in result.include


DIAGNOSTICS = [
    ("AMX002", "x = 1"),
    ("AMX100", "@plugin.on(events.TakeDamag)\ndef h(e): pass"),
    ("AMX101", "@plugin.on(events.TakeDamage)\ndef h(e):\n    print(e.dmg)"),
    ("AMX102", "@plugin.on(events.TakeDamage)\ndef h(e, extra): pass"),
    ("AMX103", "import time\n@plugin.command('/x')\ndef h(p):\n    time.sleep(1)"),
    ("AMX104", "@plugin.on(events.PutInServer)\nasync def h(e):\n    await sleep(1)\n    print(e.player)"),
    ("AMX105", "@plugin.on(events.TakeDamage, post=True)\ndef h(e):\n    e.damage = 1"),
    ("AMX106", "@plugin.on(events.TakeDamage)\ndef h(e):\n    e.victim = None"),
    ("AMX107", "@plugin.on(events.Init, post=True)\ndef h(e): pass"),
    ("AMX201", "@plugin.native\ndef n_bad(names: list[str]) -> int:\n    return 0"),
    ("AMX203", "@plugin.native\nasync def n_async(x: int) -> int:\n    return 0"),
    ("AMX301", "data = open('x.txt').read()"),
    ("AMX401", "@plugin.command('bad name')\ndef h(p): pass"),
    ("AMX405", "class S(Config, prefix='s_'):\n    n: int = cvar('abc')"),
]


@pytest.mark.parametrize(("code", "body"), DIAGNOSTICS, ids=[c for c, _ in DIAGNOSTICS])
def test_diagnostics(code: str, body: str, make_plugin: MakePlugin) -> None:
    header = "from amxpy import Config, Plugin, cvar, events, sleep\n"
    if code != "AMX002":
        header += 'plugin = Plugin("Diag")\n'
    result = compile_plugin(make_plugin("diag", header + body))
    codes = [d.code for d in result.diagnostics]
    assert code in codes, [d.format() for d in result.diagnostics]


def test_diagnostics_suggest_names(make_plugin: MakePlugin) -> None:
    result = compile_plugin(make_plugin("typo", '''
        from amxpy import Plugin, events
        plugin = Plugin("Typo")

        @plugin.on(events.TakeDamage)
        def h(e):
            e.dmg = 1
    '''))
    message = next(d for d in result.diagnostics if d.code == "AMX101").format()
    assert "typo.py:7:5" in message
    assert "может быть, damage?" in message
    assert not result.ok


def test_package_roundtrip_and_runtime_check(tmp_path: Path) -> None:
    package = compile_plugin(EXAMPLES / "vip").require()
    write_package(package, tmp_path / "vip.amxpy")
    loaded = read_package(tmp_path / "vip.amxpy")
    assert loaded.manifest == package.manifest
    assert loaded.modules.keys() == package.modules.keys()
    assert loaded.modules["perks"].code == package.modules["perks"].code
    assert loaded.modules["perks"].source == package.modules["perks"].source
    assert loaded.data == package.data
    loaded.check_runtime()

    loaded.manifest["runtime"]["magic"] = "00000000"
    with pytest.raises(PackageError, match="rebuild the plugin"):
        loaded.check_runtime()


def test_release_build_has_no_sources() -> None:
    package = compile_plugin(EXAMPLES / "hello.py", release=True).require()
    assert all(entry.source is None for entry in package.modules.values())


def test_cli_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "dist"
    assert main(["build", str(EXAMPLES / "hello.py"), str(EXAMPLES / "vip"), "-o", str(out)]) == 0
    for rel in ("hello.amxpy", "vip.amxpy", "include/vip.inc", "configs/vip.cfg", "configs/hello.cfg"):
        assert (out / rel).is_file(), rel
    printed = capsys.readouterr().out
    assert "vip" in printed and "✓" in printed


def test_cli_build_fails_on_errors(tmp_path: Path, make_plugin: MakePlugin) -> None:
    broken = make_plugin("broken", "from amxpy import Plugin\nplugin = Plugin('B')\ndef f(:\n")
    assert main(["build", str(broken), "-o", str(tmp_path / "dist")]) == 1
    assert not (tmp_path / "dist" / "broken.amxpy").exists()

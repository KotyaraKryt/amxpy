from __future__ import annotations

from amxpy.compiler import compile_plugin
from amxpy.package import write_package
from amxpy.testing import FakeServer

from .conftest import MakePlugin

COUNTER = '''
from amxpy import Player, PlayerState, Plugin, events
plugin = Plugin("Counter", version="{version}")
kills = PlayerState(int, keep=True)
starts = []

@plugin.on(events.Init)
def init(e):
    starts.append(e.hot_reload)
    plugin.keep("note", plugin.kept("note", 0) + 1)

@plugin.on(events.PlayerKilled, post=True)
def count(e):
    if e.killer is not None:
        kills[e.killer] += 1

@plugin.command("/kills")
def show(player: Player) -> None:
    player.print(f"v{version} kills={{kills.get(player, 0)}} note={{plugin.kept('note')}}")

@plugin.native
def counter_get(player: Player) -> int:
    return kills.get(player, 0) * {version}
'''


def _setup(server: FakeServer, make_plugin: MakePlugin):
    inst = server.load(make_plugin("counter", COUNTER.format(version=1)))
    alice = server.join("Alice")
    bob = server.join("Bob")
    server.kill(bob, alice)
    server.kill(bob, alice)
    return inst, alice



def _version(server: FakeServer, name: str) -> str:
    plugin = server.plugin(name).plugin
    assert plugin is not None
    return plugin.version


def test_reload_keeps_player_state(server: FakeServer, make_plugin: MakePlugin) -> None:
    _setup(server, make_plugin)
    make_plugin("counter", COUNTER.format(version=2))
    assert server.reload("counter") is True

    inst = server.plugin("counter")
    assert _version(server, "counter") == "2"
    assert inst.module.starts == [True]  # Init(hot_reload=True)
    alice = next(p for p in server.backend.clients.values() if p.name == "Alice")
    assert server.native("counter_get", alice.index) == 4  # новая реализация натива, старое состояние
    server.join("Carol").say("/kills")
    assert server.backend.clients[3].chat[-1] == "v2 kills=0 note=1"  # kept() — что сохранила v1


def test_reload_rolls_back_on_broken_version(server: FakeServer, make_plugin: MakePlugin) -> None:
    _, alice = _setup(server, make_plugin)
    make_plugin("counter", COUNTER.format(version=3) + "\nraise RuntimeError('broken release')\n")
    assert server.reload("counter") is False
    assert "broken release" in "\n".join(server.lines)

    assert _version(server, "counter") == "1"  # откат на старую версию
    alice.say("/kills")
    assert alice.last_chat == "v1 kills=2 note=1"


def test_reload_refuses_changed_native_signature(server: FakeServer, make_plugin: MakePlugin) -> None:
    _setup(server, make_plugin)
    changed = COUNTER.format(version=4).replace("def counter_get(player: Player)", "def counter_get(player: Player, k: int)")
    make_plugin("counter", changed)
    assert server.reload("counter") is False
    assert any("native counter_get changed its signature" in line for line in server.lines)
    assert _version(server, "counter") == "1"


def test_file_watch_reloads_package_from_disk(server: FakeServer, make_plugin: MakePlugin) -> None:
    plugins_dir = server.host.plugins_dir
    write_package(compile_plugin(make_plugin("counter", COUNTER.format(version=1))).require(), plugins_dir / "counter.amxpy")
    server.host.load_file("counter")
    alice = server.join("Alice")
    server.kill(server.join("Bob"), alice)

    server.set_cvar("amxpy_hotreload", "2")
    import os
    import time

    write_package(compile_plugin(make_plugin("counter", COUNTER.format(version=5))).require(), plugins_dir / "counter.amxpy")
    future = time.time() + 10  # гарантированно другое mtime
    os.utime(plugins_dir / "counter.amxpy", (future, future))
    server.run(1.2)

    assert _version(server, "counter") == "5"
    alice.say("/kills")
    assert alice.last_chat == "v5 kills=1 note=1"


def test_keep_in_on_unload_survives_reload(server: FakeServer, make_plugin: MakePlugin) -> None:
    source = '''
from amxpy import Plugin
plugin = Plugin("Rounds", version="{version}")
current = plugin.kept("round", 0) + 1

@plugin.on_unload
def save() -> None:
    plugin.keep("round", current * 10)

@plugin.on_unload
async def save_async() -> None:
    plugin.keep("async", "до первого await")
'''
    server.load(make_plugin("rounds", source.format(version=1)))
    make_plugin("rounds", source.format(version=2))
    assert server.reload("rounds") is True
    module = server.plugin("rounds").module
    assert module.current == 11  # v1 сохранила 1 * 10 в on_unload
    assert module.plugin.kept("async") == "до первого await"

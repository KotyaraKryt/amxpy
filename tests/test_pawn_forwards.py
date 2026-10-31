from __future__ import annotations

import struct
from pathlib import Path

from amxpy._bridge import FORWARD_NATIVE, OP_PROC, OP_SYSREQ_C, build_amxx, build_forwards_image, read_amxx
from amxpy.amxx import FloatRef, Ref
from amxpy.testing import FakeServer

from .conftest import MakePlugin

JAIL = """
    from amxpy import Player, Plugin, amxx

    plugin = Plugin("Jail")
    seen = []


    @plugin.on_forward("jb_day_start")
    def day_start(day: int, title: str, speed: float, warden: Player | None) -> int:
        seen.append((day, title, speed, warden.name if warden else None))
        return 1


    @plugin.on_forward("jb_day_start")
    def second(day: int) -> None:
        seen.append(("second", day))


    @plugin.on_forward("jb_give_money")
    def give_money(player: Player, amount: amxx.Ref, scale: amxx.FloatRef) -> None:
        amount.value *= 2
        scale.value = 0.5


    @plugin.on_forward("client_putinserver")
    def putin(index):
        seen.append(("putin", index))
"""


def _plugin_files(server: FakeServer) -> tuple[Path, Path]:
    amxmodx = Path(server.backend.game_dir()) / "addons" / "amxmodx"
    return amxmodx / "configs" / "plugins-amxpy.ini", amxmodx / "plugins" / "amxpy_forwards.amxx"


def test_receiver_plugin_image() -> None:
    image = build_forwards_image(["jb_day_start", "Zeta", "client_putinserver"])
    publics, natives = read_amxx(build_amxx([], image=image))
    assert [n for n, _ in publics] == ["Zeta", "client_putinserver", "jb_day_start"]  # по байтам, как amx_FindPublic
    assert natives == [FORWARD_NATIVE]
    cod = struct.unpack_from("<i", image, 4 + 2 + 1 + 1 + 2 + 2)[0]
    for index, (_, address) in enumerate(publics):
        stub = struct.unpack_from("<10i", image, cod + address)
        assert stub[0] == OP_PROC and stub[2] == index and stub[5] == OP_SYSREQ_C and stub[6] == 0


def test_pawn_forwards_reach_python_from_next_map(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("jail", JAIL))
    seen = inst.module.seen  # type: ignore[union-attr]
    ini, plugin = _plugin_files(server)
    assert ini.read_text().splitlines()[-1] == "amxpy_forwards.amxx"
    assert [n for n, _ in read_amxx(plugin.read_bytes())[0]] == ["client_putinserver", "jb_day_start", "jb_give_money"]
    assert any("from the next map" in line for line in server.lines)

    bob = server.join("Bob")
    assert server.pawn_forward("jb_day_start", 3, "Свободный день", 1.5, bob) == 0  # приёмник ещё не загружен
    server.change_map()
    assert server.pawn_forward("jb_day_start", 3, "Свободный день", 1.5, bob) == 1  # max ответов подписчиков
    assert server.pawn_forward("jb_day_start", 4, "Голодный", 0.0, 0) == 1
    assert seen == [(3, "Свободный день", 1.5, "Bob"), ("second", 3), (4, "Голодный", 0.0, None), ("second", 4)]

    amount, scale = Ref(100), FloatRef(1.0)
    server.pawn_forward("jb_give_money", bob, amount, scale)
    assert (amount.value, scale.value) == (200, 0.5)  # параметры по ссылке вернулись в Pawn

    server.pawn_forward("client_putinserver", bob.index)  # форвард ядра AMXX — тоже по имени
    assert seen[-1] == ("putin", bob.index)


def test_unsubscribed_on_unload(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("jail", JAIL))
    server.change_map()
    server.host.unload("jail")
    ini, _ = _plugin_files(server)
    assert "amxpy_forwards.amxx" not in ini.read_text().split()
    assert server.pawn_forward("jb_day_start", 1, "x", 0.0, 0) == 0  # подписчиков больше нет


def test_python_forwards_are_not_received_twice(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("emitter", '''
        from amxpy import Player, Plugin

        plugin = Plugin("Emitter")
        granted = plugin.forward("vip_granted", player=Player, days=int)
        got = []


        @plugin.on_forward("vip_granted")
        def on_granted(player: Player, days: int) -> None:
            got.append(days)


        @plugin.command("/grant")
        def grant(player: Player) -> None:
            granted.emit(player, 7)
    '''))
    _, plugin = _plugin_files(server)
    assert not plugin.exists()  # форвард объявлен в Python — приёмник для него не нужен
    bob = server.join("Bob")
    bob.say("/grant")
    assert server.plugin("emitter").module.got == [7]  # type: ignore[union-attr]


def test_boot_clears_stale_receiver(server: FakeServer) -> None:
    ini, _ = _plugin_files(server)
    ini.parent.mkdir(parents=True, exist_ok=True)
    ini.write_text("amxpy_forwards.amxx\n")  # остался от прошлого запуска с подписками
    server.host.boot()  # плагинов с подписками нет
    assert "amxpy_forwards.amxx" not in ini.read_text().split()

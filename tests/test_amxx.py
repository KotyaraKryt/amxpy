from __future__ import annotations

import struct
import zlib

import pytest

from amxpy._bridge import HEADER, build_amxx, build_image, read_natives
from amxpy.testing import FakeServer

from .conftest import MakePlugin

CALLER = """
    from amxpy import Player, Plugin, amxx, events

    plugin = Plugin("Caller")
    seen = []


    @plugin.command("/rich")
    def rich(player: Player) -> None:
        amxx.call("cs_set_user_money", player, 16000, 1)


    @plugin.command("/me")
    def me(player: Player) -> None:
        name = amxx.String(32)
        written = amxx.call("get_user_name", player, name, 31)
        origin = amxx.Array(3)
        amxx.call("get_user_origin", player, origin)
        aim = amxx.FloatRef()
        distance = amxx.call_float("get_user_aiming", player, aim)
        seen.append((name.value, written, origin.values, aim.value, distance))


    @plugin.command("/say")
    def say(player: Player, *words: str) -> None:
        amxx.call("client_print", player, 3, "%s (%d)", " ".join(words), amxx.Ref(len(words)))


    @plugin.command("/missing")
    def missing(player: Player) -> None:
        try:
            amxx.call("no_such_native", player)
        except amxx.NativeError as exc:
            seen.append(str(exc))


    @plugin.command("/broken")
    def broken(player: Player) -> None:
        try:
            amxx.call("cs_set_user_money", player, -1, 1)
        except amxx.NativeError as exc:
            seen.append(str(exc))


    @plugin.command("/thread")
    async def thread(player: Player) -> None:
        try:
            await plugin.offload(amxx.call, "cs_set_user_money", 1, 1, 1)
        except amxx.NativeError as exc:
            seen.append(str(exc))


    @plugin.on(events.Init)
    def init(e: events.Init) -> None:
        seen.append(("available", amxx.available("cs_set_user_money", "get_user_name"), amxx.available("vip_days")))
"""


def _natives(server: FakeServer) -> list[tuple[str, tuple[object, ...]]]:
    calls: list[tuple[str, tuple[object, ...]]] = []

    @server.amxx_native("cs_set_user_money")
    def cs_set_user_money(index: int, money: int, flash: int) -> int:
        if money < 0:
            raise ValueError("Invalid money amount")
        server.backend.clients[index].props["money"] = float(money)
        calls.append(("cs_set_user_money", (index, money, flash)))
        return 1

    @server.amxx_native("get_user_name")
    def get_user_name(index: int, name: object, size: int) -> int:
        name.value = server.backend.clients[index].name[:size]  # type: ignore[attr-defined]
        return len(name.value)  # type: ignore[attr-defined]

    @server.amxx_native("get_user_origin")
    def get_user_origin(index: int, origin: object) -> int:
        origin.value = [10, 20, 30]  # type: ignore[attr-defined]
        return 1

    @server.amxx_native("get_user_aiming")
    def get_user_aiming(index: int, body: object) -> float:
        body.value = 1.5  # type: ignore[attr-defined]
        return 256.25

    @server.amxx_native("client_print")
    def client_print(index: int, kind: int, fmt: str, text: str, count: object) -> int:
        calls.append(("client_print", (index, kind, fmt, text, count.value)))  # type: ignore[attr-defined]
        return 1

    return calls


def test_bridge_image_format() -> None:
    names = ["get_user_name", "cs_set_user_money"]
    image = build_image(names, heap_cells=64)
    fields = HEADER.unpack_from(image)
    size, magic, file_version, amx_version, flags, defsize, cod, dat, hea, stp = fields[:10]
    assert (magic, file_version, amx_version, defsize, flags) == (0xF1E0, 8, 8, 8, 0)
    assert size == hea == len(image) and stp == hea + 64 * 4 and cod % 4 == 0 and dat == cod + 8
    data = build_amxx(names, heap_cells=64)
    assert struct.unpack_from("<ihb", data) == (0x414D5858, 0x0300, 1)
    assert zlib.decompress(data[24:]) == image
    assert read_natives(data) == names
    with pytest.raises(ValueError):
        build_image(["a", "a"])
    with pytest.raises(ValueError):
        build_image(["x" * 64])


def test_call_with_outputs_and_varargs(server: FakeServer, make_plugin: MakePlugin) -> None:
    calls = _natives(server)
    inst = server.load(make_plugin("caller", CALLER))
    seen = inst.module.seen  # type: ignore[union-attr]
    bob = server.join("Bob")
    bob.say("/rich")
    assert bob.money == 16000
    bob.say("/me")
    bob.say("/say hello world")
    assert seen[0] == ("available", True, False)
    assert seen[1] == ("Bob", 3, [10, 20, 30], 1.5, 256.25)
    assert calls == [("cs_set_user_money", (bob.index, 16000, 1)), ("client_print", (bob.index, 3, "%s (%d)", "hello world", 2))]
    # каждое имя попадает в мост один раз, дальше — из кеша
    names = [n for b in server.backend.bridges for n in b]
    assert len(names) == len(set(names))


def test_errors(server: FakeServer, make_plugin: MakePlugin) -> None:
    _natives(server)
    inst = server.load(make_plugin("caller", CALLER))
    seen = inst.module.seen  # type: ignore[union-attr]
    bob = server.join("Bob")
    bob.say("/missing")
    bob.say("/broken")
    bob.say("/thread")
    assert "native no_such_native is not available" in seen[1]
    assert "cs_set_user_money reported an error (AMX error 10)" in seen[2]
    assert any("Invalid money amount" in line for line in server.lines)
    assert "only from the game thread" in seen[3]


def test_missing_natives_are_retried_on_map_change(server: FakeServer, make_plugin: MakePlugin) -> None:
    _natives(server)
    inst = server.load(make_plugin("caller", CALLER))
    seen = inst.module.seen  # type: ignore[union-attr]
    bob = server.join("Bob")
    bob.say("/missing")
    bob.say("/missing")
    assert sum(b.count("no_such_native") for b in server.backend.bridges) == 1  # промах кешируется до смены карты

    server.amxx_native("no_such_native")(lambda index: 7)  # Pawn-плагин новой карты зарегистрировал натив
    server.host.on_map_start("de_dust2")
    bob.say("/missing")
    assert len(seen) == 3  # третий вызов прошёл без ошибки

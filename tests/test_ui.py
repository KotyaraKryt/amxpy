from __future__ import annotations

import pytest

from amxpy import _backend as B
from amxpy.testing import FakeServer

from .conftest import EXAMPLES, MakePlugin

SHOP = '''
from amxpy import Menu, Player, Plugin
plugin = Plugin("Shop")
bought = []
shop = Menu("Магазин", per_page=3)

@shop.item("AK-47", enabled=lambda p: p.money >= 2500)
def ak(player: Player) -> None:
    bought.append("AK-47")
    player.money -= 2500

for name in ("Deagle", "HE", "Flash", "Smoke"):
    shop.add(name, lambda p, n=name: bought.append(n))

@plugin.command("/shop")
def open_shop(player: Player) -> None:
    shop.show(player)
'''

VOTE = '''
from amxpy import Menu, Player, Plugin
plugin = Plugin("Vote")
results = []

@plugin.command("/vote")
async def vote(player: Player) -> None:
    results.append(await Menu.ask(player, "Карта?", ["de_dust2", "de_inferno"], timeout=5))
'''


def test_menu_pages_disabled_items_and_callbacks(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("shop", SHOP))
    alice = server.join("Alice", money=800, lang="ru")
    alice.say("/shop")
    assert alice.menu is not None
    lines = alice.menu.splitlines()
    assert lines[0] == "Магазин1/2"
    assert lines[2:5] == ["1. AK-47", "2. Deagle", "3. HE"]
    assert lines[-3:] == ["8. Назад", "9. Далее", "0. Выход"]
    assert alice.menu_keys == 0b1100000110  # AK-47 и «Назад» недоступны

    assert alice.select(1) is True  # недоступная клавиша проглатывается
    alice.say("/shop")
    alice.select(9)
    assert alice.menu.splitlines()[0] == "Магазин2/2"
    alice.select(2)
    assert inst.module.bought == ["Smoke"]

    alice.money = 3000
    alice.say("/shop")
    alice.select(1)
    assert inst.module.bought == ["Smoke", "AK-47"]
    assert alice.money == 500


def test_menu_ask_returns_choice_none_on_exit_and_timeout(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("vote", VOTE))
    alice = server.join("Alice")
    alice.say("/vote")
    assert alice.menu is not None and alice.menu.splitlines()[-1] == "0. Exit"
    alice.select(2)
    alice.say("/vote")
    alice.select(0)
    alice.say("/vote")
    server.run(6)
    assert inst.module.results == [1, None, None]


def test_menu_yields_to_amxx_and_closes_on_unload(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("vote", VOTE))
    alice = server.join("Alice")
    alice.say("/vote")
    # нажатие уже обработало меню AMXX: наше меню закрыто, ответ — None
    assert server.host.on_client_command(alice.index, ["menuselect", "1"], "1", True) is False
    server.settle()
    assert inst.module.results == [None]
    assert alice.select(1) is False

    alice.say("/vote")
    assert alice.menu is not None
    server.unload("vote")
    assert alice.menu is None


def test_hud_and_dhud_messages(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("info", '''
        from amxpy import DirectorHud, Hud, Message, Player, Plugin
        plugin = Plugin("Info")
        hud = Hud(y=0.2, color=(0, 255, 0), channel=2)
        banner = DirectorHud(color=(255, 128, 0))

        @plugin.command("/info")
        def info(player: Player) -> None:
            hud.show(player, "Привет")
            banner.show_all("Раунд!")
            Message("ScreenFade", to=player).short(4096).short(0).short(0).byte(0).byte(0).byte(0).byte(100).send()
    '''))
    alice = server.join("Alice")
    bob = server.join("Bob")
    alice.say("/info")
    assert alice.hud == ["Привет"] and bob.hud == []
    assert alice.dhud == ["Раунд!"] and bob.dhud == ["Раунд!"]

    _, _, index, data = next(m for m in server.backend.messages if m[1] == B.SVC_TEMPENTITY)
    assert index == alice.index
    assert [v for _, v in data[:4]] == [29, 2, -8192, 1638]  # TE_TEXTMESSAGE, канал, x = -1, y = 0.2
    _, _, _, data = next(m for m in server.backend.messages if m[1] == B.SVC_DIRECTOR)
    assert data[0] == ("b", len("Раунд!".encode()) + 31)
    assert data[3] == ("l", 0xFF8000)
    assert any(m[1] == 98 and m[2] == alice.index for m in server.backend.messages)  # ScreenFade


def test_message_to_unknown_user_message_fails(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("bad", '''
        from amxpy import Message, Player, Plugin
        plugin = Plugin("Bad")

        @plugin.command("/bad")
        def bad(player: Player) -> None:
            Message("NoSuchMessage", to=player).byte(1).send()
    '''))
    server.join("Alice").say("/bad")
    assert inst.errors == 1
    assert any("unknown user message 'NoSuchMessage'" in line for line in server.lines)


@pytest.mark.parametrize("command", ["/menu", "/hud", "/dhud"])
def test_ui_demo_example(server: FakeServer, command: str) -> None:
    inst = server.load(EXAMPLES / "ui_demo.py")
    alice = server.join("Alice", lang="ru")
    alice.say(command)
    assert alice.menu or alice.hud or alice.dhud
    assert inst.errors == 0

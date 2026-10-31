from __future__ import annotations

from amxpy import MoneyReason, Team
from amxpy.testing import FakeServer

from .conftest import MakePlugin

RULES = """
    from amxpy import Access, MoneyReason, Plugin, events

    plugin = Plugin("Rules")
    log = []


    @plugin.on(events.TeamSelect)
    def no_spectators(e: events.TeamSelect) -> None:
        if e.slot == 6 and not e.player.has_access(Access.KICK):
            e.cancel()
        elif e.slot == 5:
            e.slot = 2  # автовыбор — всегда CT


    @plugin.on(events.TeamSelect, post=True)
    def joined(e: events.TeamSelect) -> None:
        log.append(("team", e.player.name, e.team))


    @plugin.on(events.MoneyChange)
    def double_kill_reward(e: events.MoneyChange) -> None:
        if e.reason == MoneyReason.ENEMY_KILLED:
            e.amount *= 2
        elif e.reason == MoneyReason.HOSTAGE_DAMAGED:
            e.cancel()


    @plugin.on(events.BuyWeapon)
    def no_awp(e: events.BuyWeapon) -> None:
        if e.weapon == "awp":
            e.cancel()


    @plugin.on(events.BuyWeapon, post=True)
    def bought(e: events.BuyWeapon) -> None:
        log.append(("buy", e.player.name, e.weapon))


    @plugin.on(events.DropItem)
    def keep_bomb(e: events.DropItem) -> None:
        if e.item == "c4":
            e.cancel()


    @plugin.on(events.DropItem, post=True)
    def dropped(e: events.DropItem) -> None:
        log.append(("drop", e.item, e.box.classname if e.box else None))


    @plugin.on(events.NameChange)
    def no_admin_names(e: events.NameChange) -> None:
        if "admin" in e.new.lower():
            e.cancel()


    @plugin.on(events.NameChange, post=True)
    def renamed(e: events.NameChange) -> None:
        log.append(("rename", e.old, e.new))


    @plugin.on(events.FreezeEnd)
    def go(e: events.FreezeEnd) -> None:
        log.append(("freeze_end",))


    @plugin.on(events.GrenadeThrow)
    def grenade(e: events.GrenadeThrow) -> None:
        log.append(("grenade", e.player.name, e.weapon, e.grenade.classname if e.grenade else None))


    @plugin.on(events.BombPlanted)
    def planted(e: events.BombPlanted) -> None:
        log.append(("planted", e.player.name if e.player else None))


    @plugin.on(events.BombDefuseStart)
    def kit_only(e: events.BombDefuseStart) -> None:
        if not e.kit:
            e.cancel()


    @plugin.on(events.BombDefuseEnd)
    def defused(e: events.BombDefuseEnd) -> None:
        log.append(("defused", e.player.name if e.player else None, e.defused))


    @plugin.on(events.BombExploded)
    def boom(e: events.BombExploded) -> None:
        log.append(("boom", e.player.name if e.player else None))
"""


def _load(server: FakeServer, make_plugin: MakePlugin) -> list[tuple[object, ...]]:
    inst = server.load(make_plugin("rules", RULES))
    assert inst.module is not None
    return inst.module.log


def test_team_select(server: FakeServer, make_plugin: MakePlugin) -> None:
    log = _load(server, make_plugin)
    bob = server.join("Bob")
    admin = server.join("Admin", flags="c")
    assert server.choose_team(bob, 6) is False
    assert server.choose_team(admin, 6) is True
    assert server.choose_team(bob, 5) is True  # плагин заменил автовыбор на CT
    assert bob.client.team == int(Team.CT)
    assert log == [("team", "Admin", Team.SPECTATOR), ("team", "Bob", Team.CT)]


def test_money_change(server: FakeServer, make_plugin: MakePlugin) -> None:
    _load(server, make_plugin)
    bob = server.join("Bob", money=800)
    assert server.give_money(bob, 300, MoneyReason.ENEMY_KILLED) == 600
    assert server.give_money(bob, -150, MoneyReason.HOSTAGE_DAMAGED) == 0
    assert server.give_money(bob, 3250, MoneyReason.ROUND_BONUS) == 3250
    assert bob.money == 800 + 600 + 3250


def test_buy_and_drop(server: FakeServer, make_plugin: MakePlugin) -> None:
    log = _load(server, make_plugin)
    bob = server.join("Bob", money=5000)
    assert server.buy(bob, "awp", price=4750) is False
    assert bob.money == 5000  # запрещённая покупка ничего не стоит
    assert server.buy(bob, "ak47", price=2500) is True
    assert bob.money == 2500 and "ak47" in bob.items
    bob.items.append("c4")
    assert server.drop(bob, "c4") is False and "c4" in bob.items
    assert server.drop(bob, "ak47") is True and "ak47" not in bob.items
    assert log == [("buy", "Bob", "ak47"), ("drop", "ak47", "weaponbox")]


def test_name_change(server: FakeServer, make_plugin: MakePlugin) -> None:
    log = _load(server, make_plugin)
    bob = server.join("Bob")
    assert server.rename(bob, "Admin_Bob") is False
    assert bob.name == "Bob"
    assert server.rename(bob, "Robert") is True
    assert bob.name == "Robert"
    assert log == [("rename", "Bob", "Robert")]


def test_freeze_end_and_grenades(server: FakeServer, make_plugin: MakePlugin) -> None:
    log = _load(server, make_plugin)
    bob = server.join("Bob")
    server.freeze_end()
    server.throw_grenade(bob, "flashbang")
    assert log == [("freeze_end",), ("grenade", "Bob", "flashbang", "grenade")]


def test_bomb(server: FakeServer, make_plugin: MakePlugin) -> None:
    log = _load(server, make_plugin)
    terror = server.join("Terror", team=Team.T)
    sapper = server.join("Sapper")
    server.plant_bomb(terror)
    assert server.defuse(sapper) is False  # без набора сапёра плагин не даёт начать
    assert server.defuse(sapper, kit=True, success=False) is True
    server.explode_bomb(terror)
    assert log == [("planted", "Terror"), ("defused", "Sapper", False), ("boom", "Terror")]
    assert server.bomb is None

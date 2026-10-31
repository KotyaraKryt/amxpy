from __future__ import annotations

from amxpy import Team
from amxpy.testing import FakeServer

from .conftest import EXAMPLES


def test_hello_greets_after_delay(server: FakeServer) -> None:
    server.load(EXAMPLES / "hello.py")
    alice = server.join("Alice")
    assert alice.chat == []
    server.run(3.1)
    assert alice.last_chat == "Привет, Alice! Набери /hp"


def test_hello_greeting_is_cancelled_when_player_leaves(server: FakeServer) -> None:
    inst = server.load(EXAMPLES / "hello.py")
    alice = server.join("Alice")
    alice.disconnect()
    server.run(5)
    assert inst.errors == 0
    assert not inst.tasks


def test_hp_command(server: FakeServer) -> None:
    server.load(EXAMPLES / "hello.py")
    alice = server.join("Alice", health=42, armor=10)
    assert alice.say("/hp") is True  # команда скрывает сообщение в чате
    assert alice.last_chat == "HP: 42, броня: 10"


def test_team_damage_is_blocked(server: FakeServer) -> None:
    server.load(EXAMPLES / "hello.py")
    ct1 = server.join("CT1", team=Team.CT)
    ct2 = server.join("CT2", team=Team.CT)
    t = server.join("T", team=Team.T)
    assert server.damage(ct2, 30, attacker=ct1) == 0
    assert ct2.health == 100
    assert server.damage(ct2, 30, attacker=t) == 30
    assert ct2.health == 70
    assert server.damage(ct1, 10, attacker=ct1) == 10  # урон по себе — не урон по своим


def test_friendly_fire_cvar(server: FakeServer) -> None:
    server.load(EXAMPLES / "hello.py", cvars={"hello_friendly_fire": 1})
    a = server.join("A")
    b = server.join("B")
    assert server.damage(b, 30, attacker=a) == 30


def test_heal_checks_access_and_parses_arguments(server: FakeServer) -> None:
    server.load(EXAMPLES / "hello.py")
    admin = server.join("Admin", flags="e")
    user = server.join("User", lang="ru")
    bob = server.join("Bob", health=20)

    user.command("amx_heal Bob 50")
    assert bob.health == 20
    assert user.last_chat == "У вас нет доступа к этой команде."

    admin.command("amx_heal Bob 50")
    assert bob.health == 70
    assert admin.console[-1] == "Bob: +50 HP"

    admin.command("amx_heal")
    assert admin.last_chat == "Usage: amx_heal <target> [amount]"
    admin.command("amx_heal Nobody")
    assert admin.last_chat == "Player not found: Nobody"
    admin.command("amx_heal Bob lots")
    assert admin.last_chat == "amount: a whole number is expected"


def test_vip_flow(server: FakeServer) -> None:
    inst = server.load(EXAMPLES / "vip", cvars={"vip_hp_bonus": 50})
    admin = server.join("Admin", flags="l")
    alice = server.join("Alice", steam_id="STEAM_0:1:42", lang="ru")
    assert server.native("vip_is_user_vip", alice) == 0
    alice.say("/vip")
    assert alice.last_chat == "У вас нет VIP"

    admin.command("amx_vip_add Alice 7")
    assert server.native("vip_is_user_vip", alice) == 1
    assert server.native("vip_days_left", alice) == 7
    assert ("vip_granted", (alice.index, 7)) in server.forwards

    server.spawn(alice)
    assert alice.health == 150
    alice.say("/vip")
    assert alice.last_chat == "VIP: осталось 7 дн."

    t = server.join("T", team=Team.T)
    assert round(server.damage(t, 10, attacker=alice), 6) == 11  # vip_damage_mult = 1.1
    assert inst.errors == 0


def test_vip_is_loaded_from_storage_on_reconnect(server: FakeServer) -> None:
    server.load(EXAMPLES / "vip")
    admin = server.join("Admin", flags="l")
    alice = server.join("Alice", steam_id="STEAM_0:1:42")
    admin.command("amx_vip_add Alice 30")
    alice.disconnect()

    again = server.join("Alice", steam_id="STEAM_0:1:42")
    assert server.native("vip_is_user_vip", again) == 1
    assert server.native("vip_days_left", again) == 30
    again.say("/vip")
    assert again.last_chat == "VIP: 30 day(s) left"


def test_no_awp_cancels_purchase(server: FakeServer) -> None:
    server.load(EXAMPLES / "no_awp.py")
    bob = server.join("Bob", money=5000)
    admin = server.join("Admin", flags="t")
    assert server.buy(bob, "awp", price=4750) is False
    assert bob.money == 5000 and bob.last_chat == "AWP на сервере запрещена"
    assert server.buy(bob, "ak47", price=2500) is True
    assert server.buy(admin, "awp", price=4750) is True


def test_no_awp_admins_cvar(server: FakeServer) -> None:
    server.load(EXAMPLES / "no_awp.py", cvars={"noawp_admins": 0})
    admin = server.join("Admin", flags="t")
    assert server.buy(admin, "awp", price=4750) is False


def test_round_mvp_announces_best_player(server: FakeServer) -> None:
    server.load(EXAMPLES / "round_mvp.py")
    alice = server.join("Alice", team=Team.CT, money=1000)
    bob = server.join("Bob", team=Team.T, money=1000)
    carl = server.join("Carl", team=Team.T)
    server.round_start()
    server.kill(bob, alice, headshot=True)
    server.kill(carl, alice)
    server.kill(alice, bob)
    server.round_end()
    assert alice.dhud[-1] == "MVP раунда: Alice — 2 убийств, 1 в голову"
    assert alice.money == 1500 and bob.money == 1000
    server.round_start()
    server.round_end()  # без убийств — без объявления
    assert len(alice.dhud) == 1


def test_welcome_back_counts_visits(server: FakeServer) -> None:
    server.load(EXAMPLES / "welcome_back.py")
    server.settle()
    bob = server.join("Bob", steam_id="STEAM_0:1:42")
    server.run(0.1)
    assert bob.last_chat == "Добро пожаловать, Bob!"
    bob.disconnect()
    bob = server.join("Bob", steam_id="STEAM_0:1:42")
    server.run(0.1)
    assert bob.last_chat.startswith("С возвращением! Визит №2, прошлый — ")

from __future__ import annotations

from pathlib import Path

import pytest

from amxpy import StaleHandleError, Team, Winner
from amxpy.testing import ConnectionRejected, FakeServer

from .conftest import MakePlugin


def test_command_arguments_are_parsed_from_annotations(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("cmds", '''
        from amxpy import Player, Plugin, Team
        plugin = Plugin("Cmds")

        @plugin.command("/echo", "!echo")
        def echo(player: Player, *words: str) -> None:
            player.print(" ".join(words))

        @plugin.command("amx_team")
        def team(player: Player, target: Player, team: Team) -> None:
            player.print(f"{target.name} -> {team.name}")

        @plugin.command("/visible", hide=False)
        def visible(player: Player) -> None:
            player.print("ok")
    '''))
    alice = server.join("Alice")
    server.join("Bobby")

    assert alice.say("/echo hello world") is True
    assert alice.last_chat == "hello world"
    assert alice.say('!echo "quoted words" x') is True
    assert alice.last_chat == "quoted words x"

    alice.command("amx_team bob ct")
    assert alice.last_chat == "Bobby -> CT"
    alice.command("amx_team #2 spectator")
    assert alice.last_chat == "Bobby -> SPECTATOR"
    alice.command("amx_team zed ct")
    assert alice.last_chat == "Player not found: zed"
    alice.command("amx_team bob red")
    assert alice.last_chat == "team: one of unassigned/t/ct/spectator"
    alice.command("amx_team")
    assert alice.last_chat == "Usage: amx_team <target> <team>"

    assert alice.say("/visible") is False
    assert alice.last_chat == "ok"
    assert alice.say("just chatting") is False
    assert server.public_chat[-1] == ("Alice", "just chatting")


def test_access_and_cooldown(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("guard", '''
        from amxpy import Access, Player, Plugin
        plugin = Plugin("Guard")

        @plugin.command("amx_secret", access=Access.BAN)
        def secret(player: Player) -> None:
            player.print("secret")

        @plugin.command("/spin", cooldown=10)
        def spin(player: Player) -> None:
            player.print("spin")
    '''))
    user = server.join("User")
    admin = server.join("Admin", flags="d")

    user.command("amx_secret")
    assert user.last_chat == "You have no access to this command."
    admin.command("amx_secret")
    assert admin.last_chat == "secret"

    user.say("/spin")
    assert user.last_chat == "spin"
    user.say("/spin")
    assert user.last_chat == "Wait 10 s."
    server.run(10.5)
    user.say("/spin")
    assert user.last_chat == "spin"


def test_events_can_be_changed_cancelled_and_answered(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("ev", '''
        from amxpy import Plugin, events
        plugin = Plugin("Events")
        seen = []

        @plugin.on(events.TakeDamage, priority=10)
        def god_mode(e):
            if e.victim.name == "God":
                return False  # ответ за игру: урон не прошёл

        @plugin.on(events.TakeDamage)
        def halve(e):
            e.damage = e.damage / 2

        @plugin.on(events.TakeDamage, post=True)
        def after(e):
            seen.append((e.victim.name, e.damage, e.result))

        @plugin.on(events.PlayerSpawn)
        def no_ghosts(e):
            if e.player.name == "Ghost":
                e.cancel()
    '''))
    alice = server.join("Alice")
    god = server.join("God")
    ghost = server.join("Ghost", alive=False)

    assert server.damage(alice, 40) == 20
    assert inst.module.seen == [("Alice", 20.0, True)]
    assert server.damage(god, 40) == 0
    assert god.health == 100
    assert server.spawn(ghost) is False
    assert ghost.alive is False
    assert server.spawn(alice) is True
    assert server.backend.hooks == {"take_damage", "player_spawn"}  # хуки включаются лениво


def test_misuse_of_events_is_reported_not_fatal(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("misuse", '''
        from amxpy import Plugin, events, sleep
        plugin = Plugin("Misuse")

        @plugin.on(events.TakeDamage, post=True)
        def too_late(e):
            e.damage = 1

        @plugin.on(events.PutInServer)
        async def after_await(e):
            await sleep(1)
            e.player.print("never")
    '''))
    alice = server.join("Alice")
    server.damage(alice, 10)
    server.run(1.5)
    assert inst.errors == 2
    text = "\n".join(server.lines)
    assert "changing a post event has no effect" in text
    assert "has already been dispatched" in text
    assert alice.health == 90


def test_handles_go_stale_and_player_state_is_cleaned(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("state", '''
        from amxpy import Plugin, PlayerState, events
        plugin = Plugin("State")
        visits = PlayerState(int)
        remembered = []

        @plugin.on(events.PutInServer)
        def remember(e):
            visits[e.player] += 1
            remembered.append(e.player)
    '''))
    alice = server.join("Alice")
    handle = inst.module.remembered[0]
    assert handle is alice.handle
    assert inst.module.visits[handle] == 1

    alice.disconnect()
    assert len(inst.module.visits) == 0
    assert handle.connected is False
    with pytest.raises(StaleHandleError):
        _ = handle.name

    bob = server.join("Bob")  # занял тот же слот
    assert bob.index == alice.index
    assert bob.handle is not handle


def test_player_tasks_are_cancelled_on_disconnect(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("waits", '''
        import asyncio
        from amxpy import Player, Plugin, sleep
        plugin = Plugin("Waits")
        cancelled = []

        @plugin.command("/wait")
        async def wait(player: Player) -> None:
            try:
                await sleep(5)
                player.print("done")
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
    '''))
    alice = server.join("Alice")
    bob = server.join("Bob")
    alice.say("/wait")
    bob.say("/wait")
    alice.disconnect()
    server.run(6)
    assert inst.module.cancelled == [True]
    assert bob.last_chat == "done"
    assert inst.errors == 0


def test_every_and_wait_for(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("timers", '''
        from amxpy import Player, Plugin, events, server
        plugin = Plugin("Timers")
        ticks = []

        @plugin.every(1.0)
        def tick() -> None:
            ticks.append(server.time)

        @plugin.command("/next")
        async def next_round(player: Player) -> None:
            ev = await plugin.wait_for(events.RoundEnd)
            player.print(f"winner {ev.winner.name}")
    '''))
    server.run(3.05)
    assert len(inst.module.ticks) == 3

    alice = server.join("Alice")
    alice.say("/next")
    assert alice.chat == []
    server.round_end(Winner.T)
    assert alice.last_chat == "winner T"


def test_cvars_autoexec_and_on_change(server: FakeServer, make_plugin: MakePlugin) -> None:
    cfg_file = server.host.base_dir / "configs" / "tune.cfg"
    cfg_file.parent.mkdir(parents=True)
    cfg_file.write_text('tune_speed "2.5"\n', encoding="utf-8")
    inst = server.load(make_plugin("tune", '''
        from amxpy import Config, Plugin, cvar
        plugin = Plugin("Tune")

        class Settings(Config, prefix="tune_"):
            speed: float = cvar(1.5, "Скорость", min=0.5, max=3.0)
            title: str = cvar("x", "Название")
            enabled: bool = cvar(True)

        cfg = plugin.include(Settings())
        changes = []

        @cfg.on_change("speed")
        def changed(old, new):
            changes.append((old, new))
    '''))
    cfg = inst.module.cfg
    assert cfg.speed == 2.5  # значение из существующего tune.cfg
    assert cfg.title == "x" and cfg.enabled is True
    server.set_cvar("tune_speed", "9")
    assert cfg.speed == 3.0  # ограничено max
    server.console('tune_speed "2"')
    server.run(0.6)
    assert inst.module.changes == [(2.5, 2.0)]
    cfg.enabled = False
    assert server.cvar("tune_enabled") == "0"


def test_autoexec_config_is_generated(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("gen", '''
        from amxpy import Config, Plugin, cvar
        plugin = Plugin("Gen")

        class Settings(Config, prefix="gen_"):
            limit: int = cvar(5, "Лимит", min=1, max=10)

        cfg = Settings()  # без include() — тоже регистрируется
    '''))
    text = (server.host.base_dir / "configs" / "gen.cfg").read_text(encoding="utf-8")
    assert '// Лимит\n// range: 1..10\ngen_limit "5"' in text
    assert server.cvar("gen_limit") == "5"


def test_natives_and_forwards(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("bank", '''
        from amxpy import Player, PlayerState, Plugin
        plugin = Plugin("Bank")
        balance = PlayerState(int)
        paid = plugin.forward("bank_paid", player=Player, amount=int, note=str)

        @plugin.native
        def bank_add(player: Player, amount: int, note: str = "") -> int:
            balance[player] += amount
            paid.emit(player, amount, note)
            return balance[player]

        @plugin.native("bank_has")
        def has(player: Player, amount: int) -> bool:
            return balance.get(player, 0) >= amount

        @plugin.native
        def bank_double(value: float) -> float:
            return value * 2

        @plugin.native
        def bank_name(player: Player) -> str:
            return player.name.upper()
    '''))
    audit = server.load(make_plugin("audit", '''
        from amxpy import Player, Plugin
        plugin = Plugin("Audit")
        log = []

        @plugin.on_forward("bank_paid")
        def on_paid(player: Player, amount: int, note: str) -> None:
            log.append((player.name, amount, note))
    '''))
    alice = server.join("Alice")
    assert server.native("bank_add", alice, 50, "gift") == 50
    assert server.forwards[-1] == ("bank_paid", (alice.index, 50, "gift"))
    assert audit.module.log == [("Alice", 50, "gift")]
    assert server.native("bank_has", alice, 40) == 1
    assert server.native("bank_has", alice, 60) == 0
    assert server.native("bank_double", 1.25) == 2.5
    assert server.native("bank_name", alice) == "ALICE"
    assert server.native("bank_add", 31, 5, "") == 0  # в слоте 31 никого: функция не вызывается
    assert server.backend.natives["bank_add"] == ("pis", "i")


def test_connect_reject_and_chat_filter(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("gate", '''
        from amxpy import Plugin, events
        plugin = Plugin("Gate")

        @plugin.on(events.Connect)
        def gate(e):
            if e.name == "Hacker":
                e.reject("No hackers")

        @plugin.on(events.Say)
        def censor(e):
            if "badword" in e.text:
                e.cancel()
    '''))
    with pytest.raises(ConnectionRejected, match="No hackers"):
        server.join("Hacker")
    alice = server.join("Alice")
    assert alice.say("this is a badword") is True
    assert server.public_chat == []
    assert alice.say("hello") is False


def test_errors_are_isolated_and_have_source_lines(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("faulty", '''
        from amxpy import Player, Plugin
        plugin = Plugin("Faulty")

        @plugin.command("/boom")
        def boom(player: Player) -> None:
            raise ValueError("kaboom")

        @plugin.command("/exit")
        def leave(player: Player) -> None:
            raise SystemExit

        @plugin.command("/ok")
        def ok(player: Player) -> None:
            player.print("still alive")
    '''))
    alice = server.join("Alice")
    alice.say("/boom")
    alice.say("/exit")
    alice.say("/ok")
    assert alice.last_chat == "still alive"
    assert inst.errors == 2
    text = "\n".join(server.lines)
    assert "ValueError: kaboom" in text
    assert 'raise ValueError("kaboom")' in text  # строка исходника в трейсбеке
    assert "faulty.py" in text


def test_server_commands_and_builtin(server: FakeServer, make_plugin: MakePlugin) -> None:
    server.load(make_plugin("admin", '''
        from amxpy import Plugin, server
        plugin = Plugin("Admin", version="2.0", author="me")

        @plugin.server_command("amx_reset")
        def reset(amount: int = 0) -> None:
            server.console(f"reset {amount}")
    '''))
    server.console("amx_reset 5")
    server.run()
    assert "reset 5" in server.lines
    server.console("amxpy list")
    server.run()
    assert any(line.split()[:3] == ["admin", "2.0", "running"] for line in server.lines)


def test_unload_stops_everything(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("noisy", '''
        from amxpy import Player, Plugin, events
        plugin = Plugin("Noisy")
        ticks = []

        @plugin.every(0.5)
        def tick() -> None:
            ticks.append(1)

        @plugin.on(events.TakeDamage)
        def hurt(e):
            e.damage = 0

        @plugin.command("/noise")
        def noise(player: Player) -> None:
            player.print("noise")
    '''))
    server.run(1.05)
    assert len(inst.module.ticks) == 2
    assert server.unload("noisy") is True
    ticks = inst.module.ticks
    server.run(2)
    assert len(ticks) == 2
    assert server.backend.hooks == set()
    alice = server.join("Alice")
    assert alice.say("/noise") is False
    assert server.damage(alice, 10) == 10


def test_team_property(server: FakeServer) -> None:
    alice = server.join("Alice", team=Team.T)
    assert alice.handle is not None and alice.handle.team is Team.T


ADVERTS = '''
    import configparser

    from amxpy import Plugin, events

    plugin = Plugin("Adverts")
    messages = []
    path = plugin.config_file("adverts.ini", default="""
        [messages]
        1 = !gНаш сайт
    """)


    @plugin.on(events.Init)
    def load(e: events.Init) -> None:
        ini = configparser.ConfigParser()
        ini.read(path, encoding="utf-8")
        messages[:] = list(ini["messages"].values())
'''


def test_config_file_is_created_once_and_kept(server: FakeServer, make_plugin: MakePlugin) -> None:
    inst = server.load(make_plugin("adverts", ADVERTS))
    path = Path(server.backend.game_dir()) / "addons" / "amxpy" / "configs" / "adverts" / "adverts.ini"
    assert inst.module.path == path  # type: ignore[union-attr]
    assert path.read_text(encoding="utf-8") == "[messages]\n1 = !gНаш сайт\n"  # без общего отступа
    assert inst.module.messages == ["!gНаш сайт"]  # type: ignore[union-attr]

    path.write_text("[messages]\n1 = своё\n", encoding="utf-8")  # владелец сервера правит файл
    assert server.reload("adverts")
    assert path.read_text(encoding="utf-8") == "[messages]\n1 = своё\n"
    assert server.plugin("adverts").module.messages == ["своё"]  # type: ignore[union-attr]


def test_config_file_stays_in_plugin_folder(server: FakeServer, make_plugin: MakePlugin) -> None:
    plugin = server.load(make_plugin("solo", 'from amxpy import Plugin\nplugin = Plugin("Solo")\n')).plugin
    assert plugin is not None
    nested = plugin.config_file("texts/ru.txt", default="привет")
    assert nested.parts[-3:] == ("solo", "texts", "ru.txt") and nested.read_text(encoding="utf-8") == "привет"
    for bad in ["", ".", "../evil.ini", "/etc/passwd", "a/../../b", "a\\b"]:
        with pytest.raises(ValueError):
            plugin.config_file(bad)

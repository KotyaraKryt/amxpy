"""Фейковый сервер для тестов плагинов: pytest без HLDS.

    def test_hp(server):
        server.load("plugins/hello.py")
        alice = server.join("Alice")
        alice.say("/hp")
        assert "HP: 100" in alice.last_chat

Время виртуальное: ``server.run(3)`` прокручивает 3 секунды кадрами мгновенно.
После каждого действия сервер досчитывает его последствия — задачи asyncio и
запросы offload() — не двигая время.
"""

from __future__ import annotations

import re
import shlex
import struct
import tempfile
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any

from .._host import Host, PluginInstance
from .._bridge import read_amxx
from ..amxx import FloatRef, Ref
from ..player import Access, MoneyReason, Player, Team, Winner
from .backend import FakeBackend, FakeClient

__all__ = ["ConnectionRejected", "FakePlayer", "FakeServer"]

DMG_BULLET = 2


class ConnectionRejected(Exception):
    """Плагин не пустил игрока (``Connect.reject()``)."""


def _client_prop(name: str) -> property:
    """Числовое поле клиента как свойство FakePlayer."""
    return property(
        lambda self: int(self.client.props[name]),
        lambda self, value: self.client.props.__setitem__(name, float(value)),
    )


class FakePlayer:
    """Игрок фейкового сервера со стороны теста."""

    def __init__(self, server: FakeServer, index: int, userid: int) -> None:
        self.server = server
        self.index = index
        self.userid = userid

    def __repr__(self) -> str:
        return f"<FakePlayer #{self.index} uid={self.userid}>"

    @property
    def client(self) -> FakeClient:
        client = self.server.backend.clients.get(self.index)
        if client is None or client.userid != self.userid:
            raise RuntimeError(f"{self!r} has left the server")
        return client

    @property
    def connected(self) -> bool:
        client = self.server.backend.clients.get(self.index)
        return client is not None and client.userid == self.userid

    @property
    def handle(self) -> Player | None:
        """Хэндл игрока в рантайме (то, что получают плагины)."""
        return self.server.host.player_at(self.index)

    # --- состояние ---
    name = property(lambda self: self.client.name)
    steam_id = property(lambda self: self.client.steam_id)
    alive = property(lambda self: self.client.alive)
    team = property(lambda self: Team(self.client.team))
    flags = property(lambda self: Access(self.client.flags))
    chat = property(lambda self: self.client.chat, doc="сообщения в чат (без цветовых кодов)")
    console = property(lambda self: self.client.console)
    center = property(lambda self: self.client.center)
    commands = property(lambda self: self.client.commands, doc="команды, выполненные у игрока (client_cmd)")

    hud = property(lambda self: self.client.hud, doc="тексты обычного HUD")
    dhud = property(lambda self: self.client.dhud, doc="тексты DHUD")
    items = property(lambda self: self.client.items, doc="оружие игрока без префикса weapon_")

    @property
    def last_chat(self) -> str:
        return self.client.chat[-1] if self.client.chat else ""

    @property
    def menu(self) -> str | None:
        """Меню на экране без кодов цвета, или None."""
        text = self.client.menu_text
        return None if text is None else re.sub(r"\\[ywrdR]", "", text)

    @property
    def menu_keys(self) -> int:
        return self.client.menu_keys

    def select(self, key: int) -> bool:
        """Нажать в меню клавишу 1–9 или 0; меню на экране закрывается, как у клиента."""
        self.client.menu_text = None
        slot = str(key or 10)  # клавиша 0 — menuselect 10
        return self.server._client_command(self, ["menuselect", slot], slot)

    health = _client_prop("health")
    armor = _client_prop("armor")
    money = _client_prop("money")
    frags = _client_prop("frags")
    deaths = _client_prop("deaths")

    # --- действия ---
    def say(self, text: str) -> bool:
        """Написать в чат; True — сообщение скрыто плагином (команда или cancel)."""
        return self.server._client_command(self, ["say", text], f'"{text}"')

    def say_team(self, text: str) -> bool:
        return self.server._client_command(self, ["say_team", text], f'"{text}"')

    def command(self, line: str) -> bool:
        """Команда в консоли игрока; True — её обработал плагин."""
        try:
            argv = shlex.split(line)
        except ValueError:
            argv = line.split()
        args = line.strip()[len(argv[0]) :].strip() if argv else ""
        return self.server._client_command(self, argv, args)

    def disconnect(self) -> None:
        self.server.disconnect(self)


class FakeServer:
    """Сервер в памяти: тот же рантайм amxpy, но бэкенд — словари, а время — виртуальное."""

    def __init__(
        self,
        *,
        game_dir: str | Path | None = None,
        max_players: int = 32,
        map_name: str = "de_dust2",
        fps: int = 100,
    ) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        if game_dir is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="amxpy-")
            game_dir = self._tmp.name
        self.fps = fps
        self.clock = 0.0
        self.backend = FakeBackend(self, Path(game_dir), max_players=max_players, map_name=map_name)
        self.host = Host(self.backend, clock=lambda: self.clock, game_dir=game_dir)
        self.kicked: list[tuple[str, str]] = []
        self.public_chat: list[tuple[str, str]] = []
        self._pending: list[str] = []
        self._next_userid = 1
        self._next_entity = 100
        self.bomb: int | None = None  # сущность заложенной бомбы
        self._sources: dict[str, Path] = {}
        self._closed = False
        self._receivers: list[str] = []  # publics плагина-приёмника, загруженного «AMXX» на этой карте
        self.host.start()
        self._load_amxx_plugins()
        self.host.on_map_start(map_name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.host.shutdown()
        if self._tmp is not None:
            self._tmp.cleanup()

    def __enter__(self) -> FakeServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ плагины

    def load(self, source: str | Path, *, cvars: dict[str, Any] | None = None) -> PluginInstance:
        """Скомпилировать плагин amxpyc и загрузить его (как на сервере после старта карты)."""
        from ..compiler import compile_plugin

        path = Path(source)
        for name, value in (cvars or {}).items():
            self.backend.cvars[name] = str(value)
            self.backend.pinned.add(name)
        result = compile_plugin(path)
        inst = self.host.load_package(result.require(), None)
        self._sources[inst.name] = path
        self.settle()
        return inst

    def reload(self, name: str, source: str | Path | None = None) -> bool:
        """Пересобрать плагин из исходника и перезагрузить его на лету."""
        from ..compiler import compile_plugin

        path = Path(source) if source is not None else self._sources[name]
        ok = self.host.reload(name, compile_plugin(path).require())
        if ok:
            self._sources[name] = path
        self.settle()
        return ok

    def unload(self, name: str) -> bool:
        ok = self.host.unload(name)
        self.settle()
        return ok

    def plugin(self, name: str) -> PluginInstance:
        return self.host.instances[name]

    # ------------------------------------------------------------------ время

    def frame(self) -> None:
        """Один кадр: выполнить отложенные серверные команды и прокачать рантайм."""
        self._flush()
        self.clock += 1.0 / self.fps
        self.backend.time = self.clock
        self.host.on_frame()

    def run(self, seconds: float = 0.0) -> None:
        """Прокрутить ``seconds`` секунд виртуального времени (минимум один кадр)."""
        end = self.clock + seconds
        self.frame()
        self.settle()
        while self.clock + 1e-9 < end:
            self.frame()
            self.settle()

    def settle(self, timeout: float = 5.0) -> None:
        """Досчитать последствия: задачи asyncio и offload(), не двигая время."""
        loop = self.host.loop
        deadline = time.monotonic() + timeout
        while self.host.inflight or loop._ready:  # type: ignore[attr-defined]
            if time.monotonic() > deadline:
                raise TimeoutError("FakeServer.settle(): async work did not finish in time")
            if self.host.inflight:
                time.sleep(0.0005)  # ждём потоки offload()
            loop.tick()

    # ------------------------------------------------------------------ игроки

    def join(
        self,
        name: str,
        *,
        steam_id: str | None = None,
        team: Team | int = Team.CT,
        flags: str | int = "",
        ip: str = "127.0.0.1",
        bot: bool = False,
        alive: bool = True,
        health: float = 100,
        armor: float = 0,
        money: int = 800,
        lang: str = "",
        authorize: bool = True,
    ) -> FakePlayer:
        """Подключить игрока: Connect → PutInServer → (на следующем кадре) Authorized."""
        free = [i for i in range(1, self.backend.max_players() + 1) if i not in self.backend.clients]
        if not free:
            raise RuntimeError("the server is full")
        index, userid = free[0], self._next_userid
        self._next_userid += 1
        client = FakeClient(
            index=index,
            userid=userid,
            name=name,
            ip=ip,
            steam_id=steam_id or f"STEAM_0:{userid % 2}:{1000 + userid}",
            bot=bot,
            team=int(team),
            flags=int(Access.from_letters(flags)) if isinstance(flags, str) else int(flags),
            alive=alive,
        )
        client.props.update(health=float(health), armor=float(armor), money=float(money))
        if lang:
            client.info["lang"] = lang
        self.backend.clients[index] = client
        reason = self.host.on_client_connect(index, name, ip)
        if reason is not None:
            del self.backend.clients[index]
            raise ConnectionRejected(reason)
        self.host.on_client_putinserver(index)
        if bot:
            client.auth = "BOT"
        elif authorize:
            client.auth = client.steam_id
        player = FakePlayer(self, index, userid)
        self.frame()  # авторизация приходит на кадре
        self.settle()
        return player

    def disconnect(self, player: FakePlayer) -> None:
        if player.connected:
            self.host.on_client_disconnect(player.index)
            del self.backend.clients[player.index]
        self.settle()

    def _client_command(self, player: FakePlayer, argv: list[str], args: str) -> bool:
        handled = self.host.on_client_command(player.index, argv, args)
        if not handled and argv and argv[0] in ("say", "say_team"):
            self.public_chat.append((player.name, argv[1] if len(argv) > 1 else ""))
        self.settle()
        return handled

    # ------------------------------------------------------------------ игровые события

    def _pre(self, hook: str, args: list[Any]) -> tuple[bool, list[Any]]:
        answer = self.host.on_event(hook, False, list(args))
        if answer is not None:
            blocked, _, new_args = answer
            if blocked:
                return True, args
            if new_args is not None:
                args = list(new_args)
        return False, args

    def spawn(self, player: FakePlayer) -> bool:
        """Возродить игрока; False — плагин отменил."""
        blocked, args = self._pre("player_spawn", [player.index])
        if not blocked:
            client = player.client
            client.alive = True
            client.props["health"] = 100.0
            self.host.on_event("player_spawn", True, args)
        self.settle()
        return not blocked

    def damage(
        self,
        victim: FakePlayer,
        amount: float,
        *,
        attacker: FakePlayer | None = None,
        damage_type: int = DMG_BULLET,
    ) -> float:
        """Нанести урон; возвращает нанесённый урон (после плагинов)."""
        source = attacker.index if attacker is not None else 0
        blocked, args = self._pre("take_damage", [victim.index, source, source, float(amount), int(damage_type)])
        dealt = 0.0
        if not blocked:
            dealt = float(args[3])
            client = victim.client
            client.props["health"] -= dealt
            self.host.on_event("take_damage", True, args, True)
            if client.props["health"] <= 0 and client.alive:
                self.kill(victim, attacker)
        self.settle()
        return dealt

    def kill(
        self, victim: FakePlayer, killer: FakePlayer | None = None, *, headshot: bool = False, weapon: str = "ak47"
    ) -> bool:
        blocked, args = self._pre("player_killed", [victim.index, killer.index if killer else 0, headshot, weapon])
        if not blocked:
            client = victim.client
            client.alive = False
            client.props["health"] = 0.0
            client.props["deaths"] += 1
            if killer is not None and killer.index != victim.index:
                killer.client.props["frags"] += 1
            self.host.on_event("player_killed", True, args)
        self.settle()
        return not blocked

    def round_start(self) -> None:
        self.host.on_event("round_start", True, [])
        self.settle()

    def round_end(self, winner: Winner = Winner.CT, *, reason: int = 0, delay: float = 5.0) -> bool:
        blocked, args = self._pre("round_end", [int(winner), int(reason), float(delay)])
        if not blocked:
            self.host.on_event("round_end", True, args)
        self.settle()
        return not blocked

    def _load_amxx_plugins(self) -> None:
        """Как AMXX на старте карты: прочитать плагин-приёмник Pawn-форвардов из plugins-amxpy.ini."""
        amxmodx = Path(self.backend.game_dir()) / "addons" / "amxmodx"
        ini = amxmodx / "configs" / "plugins-amxpy.ini"
        listed = ini.exists() and "amxpy_forwards.amxx" in ini.read_text().split()
        plugin = amxmodx / "plugins" / "amxpy_forwards.amxx"
        self._receivers = [name for name, _ in read_amxx(plugin.read_bytes())[0]] if listed and plugin.exists() else []

    def change_map(self, map_name: str = "de_dust2") -> None:
        """Смена карты: MapEnd, AMXX заново грузит плагины (в т.ч. приёмник форвардов), MapStart."""
        self.host.on_map_end()
        self.backend.map = map_name
        self._load_amxx_plugins()
        self.host.on_map_start(map_name)
        self.settle()

    def pawn_forward(self, name: str, *args: Any) -> int:
        """Pawn-плагин выполнил форвард ``name`` (ExecuteForward): вернуть итог подписчиков amxpy.

        ``int``/``bool``/``Player`` — ячейка, ``float`` — Float:, ``str`` — строка в памяти AMX,
        ``Ref``/``FloatRef`` — параметр по ссылке: после вызова в ``.value`` то, что записал Python.
        Форвард доходит, только если плагин-приёмник с ним загружен — с карты после подписки.
        """
        if name not in self._receivers:
            return 0
        memory = self.backend.amx_cells
        memory.clear()
        next_address = 0x1000
        raw: list[int] = []
        refs: list[tuple[Ref | FloatRef, int]] = []

        def alloc(cells: list[int]) -> int:
            nonlocal next_address
            address = next_address
            for i, cell in enumerate(cells):
                memory[address + 4 * i] = cell
            next_address += 4 * len(cells)
            return address

        for arg in args:
            if isinstance(arg, (Player, FakePlayer)):
                raw.append(arg.index)
            elif isinstance(arg, str):
                raw.append(alloc([*arg.encode("utf-8"), 0]))
            elif isinstance(arg, Ref):
                address = alloc([int(arg.value)])
                refs.append((arg, address))
                raw.append(address)
            elif isinstance(arg, FloatRef):
                address = alloc([struct.unpack("<i", struct.pack("<f", arg.value))[0]])
                refs.append((arg, address))
                raw.append(address)
            elif isinstance(arg, float):
                raw.append(struct.unpack("<i", struct.pack("<f", arg))[0])
            else:
                raw.append(int(arg))
        result = self.host.on_pawn_forward(self._receivers.index(name), 1, raw)
        for ref, address in refs:
            cell = memory[address]
            ref.value = struct.unpack("<f", struct.pack("<i", cell))[0] if isinstance(ref, FloatRef) else cell
        self.settle()
        return result

    def _entity(self, classname: str) -> int:
        index = self._next_entity
        self._next_entity += 1
        self.backend.entities[index] = classname
        return index

    def choose_team(self, player: FakePlayer, slot: int) -> bool:
        """Выбрать команду в меню: 1 — T, 2 — CT, 5 — авто, 6 — зрители; False — плагин не пустил."""
        blocked, args = self._pre("team_select", [player.index, int(slot)])
        if not blocked:
            slot = int(args[1])
            player.client.team = {1: int(Team.T), 2: int(Team.CT), 6: int(Team.SPECTATOR)}.get(slot, int(Team.T))
            self.host.on_event("team_select", True, args, True)
        self.settle()
        return not blocked

    def give_money(
        self, player: FakePlayer, amount: int, reason: MoneyReason | int = MoneyReason.NONE, *, track: bool = True
    ) -> int:
        """Начислить (или списать) деньги, как игра; возвращает итоговое изменение после плагинов."""
        blocked, args = self._pre("money_change", [player.index, int(amount), int(reason), bool(track)])
        if blocked:
            self.settle()
            return 0
        props = player.client.props
        before = props["money"]
        props["money"] = float(max(0, min(16000, before + int(args[1]))))
        self.host.on_event("money_change", True, args)
        self.settle()
        return int(props["money"] - before)

    def buy(self, player: FakePlayer, weapon: str, *, price: int = 0) -> bool:
        """Купить оружие (без префикса weapon_); False — плагин запретил."""
        blocked, args = self._pre("buy_weapon", [player.index, weapon])
        if not blocked:
            player.client.items.append(weapon)
            self.host.on_event("buy_weapon", True, args)
            if price:
                self.give_money(player, -price, MoneyReason.BOUGHT_SOMETHING)
        self.settle()
        return not blocked

    def drop(self, player: FakePlayer, item: str) -> bool:
        """Выбросить предмет; False — плагин не дал."""
        blocked, args = self._pre("drop_item", [player.index, item, 0])
        if not blocked and item in player.client.items:
            player.client.items.remove(item)
            args[2] = self._entity("weaponbox")
            self.host.on_event("drop_item", True, args)
        self.settle()
        return not blocked

    def rename(self, player: FakePlayer, name: str) -> bool:
        """Сменить ник; False — плагин оставил старый."""
        blocked, args = self._pre("name_change", [player.index, player.client.name, name])
        if not blocked:
            player.client.name = name
            self.host.on_event("name_change", True, args, True)
        self.settle()
        return not blocked

    def freeze_end(self) -> None:
        self.host.on_event("freeze_end", True, [])
        self.settle()

    def throw_grenade(self, player: FakePlayer, weapon: str = "hegrenade") -> int:
        """Бросить гранату; возвращает индекс сущности гранаты."""
        grenade = self._entity("grenade")
        self.host.on_event("grenade_throw", True, [player.index, grenade, weapon])
        self.settle()
        return grenade

    def plant_bomb(self, player: FakePlayer) -> int:
        """Заложить бомбу; возвращает индекс её сущности."""
        if "c4" in player.client.items:
            player.client.items.remove("c4")
        self.bomb = self._entity("grenade")
        self.host.on_event("bomb_planted", True, [player.index, self.bomb])
        self.settle()
        return self.bomb

    def defuse(self, player: FakePlayer, *, kit: bool = False, success: bool = True) -> bool:
        """Начать разминирование и закончить его (успешно или нет); False — плагин не дал начать."""
        if self.bomb is None:
            raise RuntimeError("the bomb is not planted")
        blocked, args = self._pre("bomb_defuse_start", [player.index, self.bomb, kit])
        if blocked:
            self.settle()
            return False
        self.host.on_event("bomb_defuse_start", True, args)
        self.host.on_event("bomb_defuse_end", True, [player.index, self.bomb, success])
        if success:
            self.backend.entities.pop(self.bomb, None)
            self.bomb = None
        self.settle()
        return True

    def explode_bomb(self, planter: FakePlayer | None = None) -> None:
        if self.bomb is None:
            raise RuntimeError("the bomb is not planted")
        self.host.on_event("bomb_exploded", True, [planter.index if planter else 0, self.bomb])
        self.backend.entities.pop(self.bomb, None)
        self.bomb = None
        self.settle()

    # ------------------------------------------------------------------ консоль, cvar'ы, нативы

    def console(self, line: str) -> None:
        """Строка в серверной консоли (как rcon)."""
        self._server_command(line)
        self.settle()

    def amxx_native(self, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Подставить натив AMXX для ``amxx.call(...)`` плагина.

        Функция получает аргументы по порядку: числа, float и строки — как есть,
        выходные (``String``, ``Ref``, ``Array``...) — объектом с ``.value``.
        Исключение в ней — ошибка натива (``NativeError`` у плагина).

        ```python
        @server.amxx_native("get_user_name")
        def get_user_name(index, name, size):
            name.value = server.backend.clients[index].name
            return len(name.value)
        ```
        """

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.backend.amxx_natives[name] = fn
            return fn

        return deco

    def native(self, name: str, *args: Any) -> Any:
        """Вызвать натив плагина так, как его вызвал бы Pawn-плагин."""
        raw = [a.index if isinstance(a, (FakePlayer, Player)) else a for a in args]
        result = self.host.call_native(name, raw)
        self.settle()
        return result

    def cvar(self, name: str) -> str | None:
        return self.backend.cvars.get(name)

    def set_cvar(self, name: str, value: Any) -> None:
        self.backend.cvars[name] = str(value)

    @property
    def lines(self) -> list[str]:
        """Консоль и журнал сервера."""
        return self.backend.lines

    @property
    def forwards(self) -> list[tuple[str, tuple[Any, ...]]]:
        """Форварды, отправленные Pawn-плагинам: (имя, аргументы)."""
        return self.backend.forwards

    def _server_command(self, command: str) -> None:
        """Серверная команда — как в движке: попадает в буфер и выполняется на кадре."""
        self._pending.append(command)

    def _flush(self) -> None:
        while self._pending:
            self._execute(self._pending.pop(0))

    def _execute(self, command: str) -> None:
        try:
            argv = shlex.split(command)
        except ValueError:
            argv = command.split()
        if not argv:
            return
        name = argv[0].lower()
        if name == "exec" and len(argv) > 1:
            path = Path(self.backend.game_dir()) / argv[1]
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.split("//", 1)[0].strip()
                    if line:
                        self._execute(line)
        elif name == "kick" and len(argv) > 1 and argv[1][1:].isdigit():
            uid = int(argv[1][1:])
            for client in list(self.backend.clients.values()):
                if client.userid == uid:
                    self.kicked.append((client.name, argv[2] if len(argv) > 2 else ""))
                    self.host.on_client_disconnect(client.index)
                    del self.backend.clients[client.index]
        elif name in self.backend.engine_commands:
            self.host.on_server_command(argv)
        elif name in self.backend.cvars and len(argv) > 1:
            if name not in self.backend.pinned:
                self.backend.cvars[name] = argv[1]

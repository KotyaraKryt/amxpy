"""Игроки и сущности: хэндлы с защитой от «чужого игрока в слоте»."""

from __future__ import annotations

import enum
import re
from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any, Generic, Self, TypeVar, overload

from . import _backend as B
from . import _state, context

if TYPE_CHECKING:
    from ._host import Host

T = TypeVar("T")
D = TypeVar("D")


class StaleHandleError(RuntimeError):
    """Игрок вышел (или сущность удалена), а хэндл всё ещё используется.

    Защищает от действий над чужим игроком, занявшим тот же слот. Проверить
    заранее — ``player.connected``.
    """


class Team(enum.IntEnum):
    """Команда игрока: ``player.team == Team.CT``."""
    UNASSIGNED = 0
    T = 1
    CT = 2
    SPECTATOR = 3


class Winner(enum.IntEnum):
    """Итог раунда (WinStatus ReGameDLL): ``e.winner`` в :class:`events.RoundEnd`."""

    NONE = 0
    CT = 1
    T = 2
    DRAW = 3


class MoneyReason(enum.IntEnum):
    """За что меняются деньги (RewardType ReGameDLL): ``e.reason`` в :class:`events.MoneyChange`."""

    NONE = 0
    ROUND_BONUS = 1
    PLAYER_RESET = 2
    PLAYER_JOIN = 3
    PLAYER_SPEC_JOIN = 4
    BOUGHT_SOMETHING = 5
    HOSTAGE_TOOK = 6
    HOSTAGE_RESCUED = 7
    HOSTAGE_DAMAGED = 8
    HOSTAGE_KILLED = 9
    TEAMMATES_KILLED = 10
    ENEMY_KILLED = 11
    INTO_GAME = 12
    VIP_KILLED = 13
    VIP_RESCUED_MYSELF = 14


class Access(enum.IntFlag):
    """Флаги доступа администраторов AMXX (буквы a–z из users.ini).

    #### Пример
    ```python
    @plugin.command("amx_kick2", access=Access.KICK)
    def kick(admin: Player, target: Player) -> None: ...

    if player.has_access(Access.BAN | Access.KICK): ...
    ```
    """

    NONE = 0
    IMMUNITY = 1 << 0  # a
    RESERVATION = 1 << 1  # b
    KICK = 1 << 2  # c
    BAN = 1 << 3  # d
    SLAY = 1 << 4  # e
    MAP = 1 << 5  # f
    CVAR = 1 << 6  # g
    CFG = 1 << 7  # h
    CHAT = 1 << 8  # i
    VOTE = 1 << 9  # j
    PASSWORD = 1 << 10  # k
    RCON = 1 << 11  # l
    LEVEL_A = 1 << 12  # m
    LEVEL_B = 1 << 13  # n
    LEVEL_C = 1 << 14  # o
    LEVEL_D = 1 << 15  # p
    LEVEL_E = 1 << 16  # q
    LEVEL_F = 1 << 17  # r
    LEVEL_G = 1 << 18  # s
    LEVEL_H = 1 << 19  # t
    MENU = 1 << 20  # u
    BAN_TEMP = 1 << 21  # v
    ADMIN = 1 << 24  # y
    USER = 1 << 25  # z

    @classmethod
    def from_letters(cls, letters: str) -> Access:
        """Флаги по буквам users.ini: ``Access.from_letters("bcd")``."""
        value = 0
        for ch in letters.lower():
            if "a" <= ch <= "z":
                value |= 1 << (ord(ch) - ord("a"))
        return cls(value)


_COLORS = {"!g": "\x04", "!t": "\x03", "!y": "\x01", "!n": "\x01"}
_COLOR_RE = re.compile(r"![gtyn]")


def colorize(text: str) -> str:
    """Теги цвета чата → коды SayText.

    ``!g`` — зелёный, ``!t`` — цвет команды (красный, синий или серый),
    ``!y`` и ``!n`` — обычный жёлтый. ``player.print`` вызывает её сама.
    """
    text = _COLOR_RE.sub(lambda m: _COLORS[m.group(0)], text)
    if not text.startswith(("\x01", "\x03", "\x04")):
        text = "\x01" + text
    return text


def strip_colors(text: str) -> str:
    """Убрать теги и коды цвета: текст как его видит человек."""
    return _COLOR_RE.sub("", text).translate({1: None, 3: None, 4: None})


class _Prop(Generic[T]):
    """Числовое свойство игрока, которое читается и пишется через бэкенд."""

    __slots__ = ("key", "cast")

    def __init__(self, key: str, cast: Callable[[float], T]) -> None:
        self.key = key
        self.cast = cast

    @overload
    def __get__(self, player: None, owner: type[Any] | None = None) -> Self: ...
    @overload
    def __get__(self, player: Player, owner: type[Any] | None = None) -> T: ...
    def __get__(self, player: Player | None, owner: type[Any] | None = None) -> Self | T:
        if player is None:
            return self
        return self.cast(player._backend().get_prop(player.index, self.key))

    def __set__(self, player: Player, value: float) -> None:
        player._backend().set_prop(player.index, self.key, float(value))


class Player:
    """Хэндл игрока: слот + userid подключения.

    На одно подключение — один объект: события, команды и нативы отдают
    его же, поэтому игрока можно класть в словари и сравнивать через ``is``.
    После выхода игрока любое обращение к нему — :class:`StaleHandleError`,
    а не действие над тем, кто занял его слот. Данные плагина по игрокам
    удобно хранить в :class:`PlayerState`.

    #### Пример
    ```python
    player.print(f"!gПривет, !t{player.name}")
    player.health += 25
    if player.team == Team.CT and player.has_access(Access.KICK): ...
    ```
    """

    __slots__ = ("_host", "index", "userid", "_gone", "_authorized", "_tasks", "_menu", "__weakref__")

    def __init__(self, host: Host, index: int, userid: int) -> None:
        self._host = host
        self.index = index
        self.userid = userid
        self._gone = False
        self._authorized = False
        self._tasks: set[Any] = set()
        self._menu: Any = None  # открытое меню amxpy (_host._OpenMenu)

    def __repr__(self) -> str:
        state = "" if self.connected else " gone"
        return f"<Player #{self.index} uid={self.userid}{state}>"

    def __reduce__(self) -> tuple[Any, ...]:
        # для pickle при горячей перезагрузке: восстанавливается по слоту и userid
        return (_restore_player, (self.index, self.userid))

    @property
    def connected(self) -> bool:
        """Игрок всё ещё на сервере. После выхода любое обращение к хэндлу — StaleHandleError."""
        return not self._gone and self._host.backend.userid(self.index) == self.userid

    def _backend(self) -> B.Backend:
        if not self.connected:
            raise StaleHandleError(f"player #{self.index} (userid {self.userid}) has left the server")
        return self._host.backend

    # --- данные ---
    @property
    def name(self) -> str:
        """Ник игрока."""
        return self._backend().player_name(self.index)

    @property
    def steam_id(self) -> str:
        """SteamID (``STEAM_0:1:123``); до события Authorized может быть пустым или ``STEAM_ID_PENDING``."""
        return self._backend().player_auth(self.index)

    @property
    def ip(self) -> str:
        """IP-адрес без порта."""
        return self._backend().player_ip(self.index)

    @property
    def bot(self) -> bool:
        """Бот (fake client)."""
        return self._backend().is_bot(self.index)

    @property
    def alive(self) -> bool:
        """Жив ли игрок сейчас."""
        return self._backend().is_alive(self.index)

    @property
    def team(self) -> Team:
        """Команда: ``Team.T``, ``Team.CT``, ``Team.SPECTATOR`` или ``Team.UNASSIGNED``."""
        return Team(self._backend().player_team(self.index))

    @property
    def flags(self) -> Access:
        """Флаги доступа администратора (users.ini); проверка — :meth:`has_access`."""
        return Access(self._backend().player_flags(self.index))

    @property
    def language(self) -> str:
        """Язык игрока (setinfo lang), иначе язык сервера (amx_language)."""
        lang = self._backend().player_info(self.index, "lang")
        return lang or self._host.backend.cvar_get("amx_language") or "en"

    def info(self, key: str) -> str:
        """Значение setinfo игрока: ``player.info("_vgui_menus")``."""
        return self._backend().player_info(self.index, key)

    health = _Prop("health", int)
    """Здоровье; можно менять: ``player.health += 25``."""
    armor = _Prop("armor", int)
    """Броня (0–255); можно менять."""
    frags = _Prop("frags", int)
    """Фраги на табло; можно менять."""
    deaths = _Prop("deaths", int)
    """Смерти на табло; можно менять."""
    money = _Prop("money", int)
    """Деньги ($0–16000); можно менять."""

    # --- действия ---
    def print(self, text: str) -> None:
        """Сообщение в чат игроку.

        Теги цвета: ``!g`` — зелёный, ``!t`` — цвет команды, ``!y`` — обычный.

        #### Пример
        ```python
        player.print(f"!gVIP!y активен ещё !t{days}!y дней")
        ```
        """
        self._backend().client_print(self.index, B.PRINT_CHAT, colorize(text))

    def console(self, text: str) -> None:
        """Строка в консоль игрока (``~``)."""
        self._backend().client_print(self.index, B.PRINT_CONSOLE, text + "\n")

    def center(self, text: str) -> None:
        """Текст по центру экрана; для оформленного текста — :class:`amxpy.Hud`."""
        self._backend().client_print(self.index, B.PRINT_CENTER, text)

    def command(self, command: str) -> None:
        """Выполнить команду в консоли игрока (client_cmd).

        Клиент может запретить часть команд (``cl_filterstuffcmd``).

        #### Пример
        ```python
        player.command("spk buttons/bell1")
        ```
        """
        self._backend().client_command(self.index, command)

    def kick(self, reason: str = "") -> None:
        """Кикнуть игрока; ``reason`` он увидит в сообщении об отключении.

        #### Пример
        ```python
        player.kick("Запрещённый ник")
        ```
        """
        self._backend().server_command(f'kick #{self.userid} "{reason.replace(chr(34), chr(39))}"')

    def tr(self, key: str, **params: Any) -> str:
        """Перевод из ``lang/<язык>.toml`` плагина на языке игрока.

        Порядок поиска: язык игрока → ``en`` → любой файл → сам ключ.

        #### Пример
        ```python
        # lang/ru.toml:  welcome = "Привет, {name}!"
        player.print(player.tr("welcome", name=player.name))
        ```
        """
        inst = context.instance()
        if inst is None:
            raise RuntimeError("Player.tr() works only inside plugin code")
        return inst.translate(self.language, key, **params)

    def has_access(self, flags: Access | int) -> bool:
        """Есть ли у игрока все указанные флаги.

        #### Пример
        ```python
        if player.has_access(Access.BAN | Access.KICK): ...
        ```
        """
        return (int(self.flags) & int(flags)) == int(flags)

    def is_teammate(self, other: Player | None) -> bool:
        """Другой игрок той же команды (T или CT); сам себе игрок не тиммейт.

        #### Пример
        ```python
        if e.attacker is not None and e.attacker.is_teammate(e.victim):
            e.cancel()
        ```
        """
        if other is None or other is self:
            return False
        return self.team == other.team and self.team in (Team.T, Team.CT)


def _restore_player(index: int, userid: int) -> Player:
    host = _state.current()
    player = host.players.get(index)
    if player is not None and player.userid == userid:
        return player
    gone = Player(host, index, userid)
    gone._gone = True
    return gone


class Entity:
    """Хэндл сущности по индексу edict: оружие, гранаты, объекты карты."""

    __slots__ = ("_host", "index")

    def __init__(self, host: Host, index: int) -> None:
        self._host = host
        self.index = index

    def __repr__(self) -> str:
        return f"<Entity #{self.index} {self.classname or '?'}>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Entity) and other.index == self.index

    def __hash__(self) -> int:
        return hash(("entity", self.index))

    @property
    def classname(self) -> str:
        """Classname сущности (``weapon_ak47``, ``func_breakable``); пусто — сущности нет."""
        return self._host.backend.entity_classname(self.index)

    @property
    def valid(self) -> bool:
        """Сущность существует."""
        return bool(self.classname)


class PlayerState(Generic[T]):
    """Данные плагина по игрокам: ``state[player]``.

    Запись удаляется сама, когда игрок выходит. С ``factory`` значение
    создаётся при первом обращении. С ``keep=True`` данные переживают
    горячую перезагрузку плагина (переносятся через pickle).

    #### Параметры
    - `factory` — значение по умолчанию для нового игрока (``int``, ``list``, класс).
    - `keep` — сохранять данные при горячей перезагрузке.

    #### Пример
    ```python
    kills: PlayerState[int] = PlayerState(int, keep=True)

    @plugin.on(events.PlayerKilled, post=True)
    def count(e: events.PlayerKilled) -> None:
        if e.killer is not None:
            kills[e.killer] += 1
    ```
    """

    def __init__(self, factory: Callable[[], T] | None = None, *, keep: bool = False) -> None:
        self._data: dict[Player, T] = {}
        self._factory = factory
        self.keep = keep
        owner = context.instance()
        if owner is not None:
            owner.states.append(self)

    def __getitem__(self, player: Player) -> T:
        try:
            return self._data[player]
        except KeyError:
            if self._factory is None:
                raise
        if not player.connected:
            raise StaleHandleError(f"player #{player.index} has left the server")
        value = self._data[player] = self._factory()
        return value

    def __setitem__(self, player: Player, value: T) -> None:
        if not player.connected:
            raise StaleHandleError(f"player #{player.index} has left the server")
        self._data[player] = value

    def __delitem__(self, player: Player) -> None:
        del self._data[player]

    def __contains__(self, player: object) -> bool:
        return player in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self) -> Iterator[Player]:
        return iter(list(self._data))

    @overload
    def get(self, player: Player | None) -> T | None: ...
    @overload
    def get(self, player: Player | None, default: D) -> T | D: ...
    def get(self, player: Player | None, default: Any = None) -> Any:
        """Значение игрока или ``default``; ``None`` вместо игрока тоже допустим."""
        return self._data.get(player, default) if player is not None else default

    @overload
    def pop(self, player: Player) -> T | None: ...
    @overload
    def pop(self, player: Player, default: D) -> T | D: ...
    def pop(self, player: Player, default: Any = None) -> Any:
        """Удалить запись игрока и вернуть её (или ``default``)."""
        return self._data.pop(player, default)

    def items(self) -> list[tuple[Player, T]]:
        """Пары (игрок, значение) — копия, можно менять состояние в цикле."""
        return list(self._data.items())

    def values(self) -> list[T]:
        """Значения всех игроков."""
        return list(self._data.values())

    def clear(self) -> None:
        """Удалить данные всех игроков."""
        self._data.clear()

    # --- для хоста ---
    def _drop(self, player: Player) -> None:
        self._data.pop(player, None)

    def _dump(self) -> list[tuple[int, int, T]]:
        return [(p.index, p.userid, v) for p, v in self._data.items()]

    def _restore(self, players: dict[int, Player], rows: list[tuple[int, int, T]]) -> None:
        for index, userid, value in rows:
            player = players.get(index)
            if player is not None and player.userid == userid:
                self._data[player] = value

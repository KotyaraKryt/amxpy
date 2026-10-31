"""Каталог событий.

Обработчик получает объект события. Объект живёт, пока идёт рассылка:
до конца обработчика или до первого ``await`` в async-обработчике. Что нужно
позже — скопируйте в переменные заранее.

В pre-обработчике можно менять изменяемые поля, отменить действие игры
(:meth:`Event.cancel`) или ответить за игру (``e.result = ...`` либо
``return значение``). Post-обработчик видит итог и ничего не меняет.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Literal, Self, TypeVar, overload

from .player import MoneyReason, Team, Winner

if TYPE_CHECKING:
    from ._host import Host
    from .player import Entity, Player

T = TypeVar("T")


class EventError(RuntimeError):
    """Недопустимое действие с событием."""


class EventExpiredError(EventError):
    """Событие уже разослано (обычно — обращение после ``await``)."""


class Field(Generic[T]):
    """Поле события: позиция в сырых аргументах бэкенда + тип.

    Тип значения следует из ``kind``, и его видит редактор: ``Field(3, "float")`` —
    ``float``, ``Field(0, "player")`` — ``Player``, ``Field(2, "player?")`` — ``Player | None``.
    """

    __slots__ = ("index", "kind", "mutable", "doc", "name")

    @overload
    def __init__(
        self: Field[str], index: int, kind: Literal["str"] = ..., *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    @overload
    def __init__(
        self: Field[Player], index: int, kind: Literal["player"], *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    @overload
    def __init__(
        self: Field[Player | None], index: int, kind: Literal["player?"], *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    @overload
    def __init__(
        self: Field[Player | Entity | None], index: int, kind: Literal["entity"], *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    @overload
    def __init__(
        self: Field[float], index: int, kind: Literal["float"], *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    @overload
    def __init__(self: Field[int], index: int, kind: Literal["int"], *, mutable: bool = ..., doc: str = ...) -> None: ...
    @overload
    def __init__(
        self: Field[bool], index: int, kind: Literal["bool"], *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    @overload
    def __init__(
        self: Field[Winner], index: int, kind: Literal["winner"], *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    @overload
    def __init__(
        self: Field[MoneyReason], index: int, kind: Literal["money_reason"], *, mutable: bool = ..., doc: str = ...
    ) -> None: ...
    def __init__(self, index: int, kind: str = "str", *, mutable: bool = False, doc: str = "") -> None:
        self.index = index
        self.kind = kind
        self.mutable = mutable
        self.doc = doc
        self.name = ""

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    @overload
    def __get__(self, ev: None, owner: type[Any] | None = None) -> Self: ...
    @overload
    def __get__(self, ev: Event, owner: type[Any] | None = None) -> T: ...
    def __get__(self, ev: Event | None, owner: type[Any] | None = None) -> Self | T:
        if ev is None:
            return self
        ev._check()
        return _decode(ev._host, self.kind, ev._args[self.index])

    def __set__(self, ev: Event, value: T) -> None:
        if not self.mutable:
            raise AttributeError(f"{type(ev).__name__}.{self.name} is read-only")
        ev._check()
        if ev.post:
            raise EventError(f"{type(ev).__name__}.{self.name}: changing a post event has no effect")
        ev._args[self.index] = _encode(self.kind, value)
        ev._changed = True


def _decode(host: Host, kind: str, raw: Any) -> Any:
    if kind == "str":
        return str(raw)
    if kind in ("player", "player?"):
        return host.player_at(raw)
    if kind == "entity":
        return host.entity_at(raw)
    if kind == "float":
        return float(raw)
    if kind == "int":
        return int(raw)
    if kind == "bool":
        return bool(raw)
    if kind == "winner":
        return Winner(raw)
    if kind == "money_reason":
        try:
            return MoneyReason(raw)
        except ValueError:  # причина из новой ReGameDLL
            return int(raw)
    return raw


def _encode(kind: str, value: Any) -> Any:
    if kind == "str":
        return str(value)
    if kind in ("player", "player?", "entity"):
        return 0 if value is None else value.index
    if kind == "float":
        return float(value)
    if kind in ("int", "winner", "money_reason"):
        return int(value)
    if kind == "bool":
        return bool(value)
    return value


class Event:
    """Базовый класс событий; обработчики объявляются через ``@plugin.on(events.Имя)``.

    Объект события живёт, пока идёт рассылка: до конца обработчика или до
    первого ``await``. В pre-фазе можно менять изменяемые поля, отменить действие
    игры (:meth:`cancel`) и ответить за игру (``e.result = ...`` или ``return``).
    """

    hook: ClassVar[str | None] = None  # хук бэкенда; None — событие рассылает сам рантайм
    phases: ClassVar[tuple[bool, ...]] = (False,)  # False — pre, True — post
    cancellable: ClassVar[bool] = True
    has_result: ClassVar[bool] = False
    scope: ClassVar[str | None] = None  # поле с игроком: задачи обработчика живут, пока он на сервере

    __slots__ = ("_host", "_args", "post", "_alive", "_cancelled", "_stopped", "_changed", "_answered", "_result")

    def __init__(self, host: Host, args: list[Any], post: bool = False, result: Any = None) -> None:
        self._host = host
        self._args = args
        self.post = post
        self._alive = True
        self._cancelled = False
        self._stopped = False
        self._changed = False
        self._answered = False
        self._result = result

    @classmethod
    def fields(cls) -> dict[str, Field[Any]]:
        out: dict[str, Field[Any]] = {}
        for klass in reversed(cls.__mro__):
            for name, value in vars(klass).items():
                if isinstance(value, Field):
                    out[name] = value
        return out

    def _check(self) -> None:
        if not self._alive:
            raise EventExpiredError(
                f"{type(self).__name__} has already been dispatched; copy the fields you need before the first await"
            )

    def _expire(self) -> None:
        self._alive = False

    def _snapshot(self) -> SimpleNamespace:
        return SimpleNamespace(**{name: getattr(self, name) for name in self.fields()})

    def cancel(self) -> None:
        """Отменить действие игры (только в pre-обработчике).

        #### Исключения
        - `EventError` — событие нельзя отменить или это post-фаза.

        #### Пример
        ```python
        @plugin.on(events.TakeDamage)
        def god_mode(e: events.TakeDamage) -> None:
            if e.victim in gods:
                e.cancel()
        ```
        """
        self._check()
        if not self.cancellable:
            raise EventError(f"{type(self).__name__} cannot be cancelled")
        if self.post:
            raise EventError(f"{type(self).__name__}: a post event has already happened")
        self._cancelled = True

    def stop(self) -> None:
        """Не вызывать следующие обработчики этого события (в том числе других плагинов)."""
        self._stopped = True

    @property
    def cancelled(self) -> bool:
        """True — действие игры отменено одним из обработчиков."""
        return self._cancelled

    @property
    def result(self) -> Any:
        """Ответ игры (в post) или ответ, назначенный обработчиком (в pre).

        Назначить можно только у событий с результатом (``Connect``, ``TakeDamage``)
        и только в pre: ``e.result = 0``. То же самое — ``return значение``.
        """
        self._check()
        return self._result

    @result.setter
    def result(self, value: Any) -> None:
        self._check()
        if not self.has_result:
            raise EventError(f"{type(self).__name__} has no result")
        if self.post:
            raise EventError(f"{type(self).__name__}: a post event has already happened")
        self._result = value
        self._answered = True

    def __repr__(self) -> str:
        if not self._alive:
            return f"<{type(self).__name__} expired>"
        values = ", ".join(f"{n}={getattr(self, n)!r}" for n in self.fields())
        return f"<{type(self).__name__}{' post' if self.post else ''} {values}>"


# --- жизненный цикл плагина (рассылает рантайм) ---


class Init(Event):
    """Плагин запущен: сервер стартовал или плагин загружен или перезагружен.

    Здесь — подготовка, которой не место при импорте модуля: создать таблицы,
    открыть соединения, прочитать файлы.

    #### Поля
    - `hot_reload: bool` — True — плагин перезагружен на лету, False — обычный старт

    #### Пример
    ```python
    @plugin.on(events.Init)
    async def setup(e: events.Init) -> None:
        await table.create()
    ```
    """

    cancellable = False
    hot_reload = Field(0, "bool", doc="True — горячая перезагрузка")
    """True — плагин перезагружен на лету, False — обычный старт."""


class MapStart(Event):
    """Карта загружена, Pawn-плагины инициализированы.

    #### Поля
    - `map: str` — имя карты: ``de_dust2``

    #### Пример
    ```python
    @plugin.on(events.MapStart)
    def map_start(e: events.MapStart) -> None:
        plugin.log.info("карта %s", e.map)
    ```
    """

    cancellable = False
    map = Field(0)
    """Имя карты: ``de_dust2``."""


class MapEnd(Event):
    """Карта заканчивается: последний шанс сохранить статистику раундов.

    #### Поля
    - `map: str` — имя карты, которая заканчивается
    """

    cancellable = False
    map = Field(0)
    """Имя карты, которая заканчивается."""


class Unload(Event):
    """Плагин останавливается: ``reason`` — ``"reload"``, ``"unload"`` или ``"shutdown"``.

    При ``"reload"`` состояние можно передать новой версии через ``plugin.keep()``
    или ``PlayerState(keep=True)``.

    #### Поля
    - `reason: str` — "reload", "unload" или "shutdown"
    """

    cancellable = False
    reason = Field(0)
    """"reload", "unload" или "shutdown"."""


class Frame(Event):
    """Каждый кадр сервера (сотни раз в секунду).

    Дорогое событие: для периодической работы используйте ``@plugin.every(сек)``.
    """

    cancellable = False


# --- игроки (рассылает рантайм) ---


class Connect(Event):
    """Игрок подключается; ``e.reject("причина")`` — не пускать.

    SteamID ещё не известен — проверки по нему делайте в :class:`Authorized`.

    #### Поля
    - `player: Player` — подключающийся игрок
    - `name: str` — ник при подключении
    - `ip: str` — IP-адрес без порта

    #### Пример
    ```python
    @plugin.on(events.Connect)
    def no_bad_names(e: events.Connect) -> None:
        if "admin" in e.name.lower():
            e.reject("Ник занят")
    ```
    """

    has_result = True
    scope = "player"
    player = Field(0, "player")
    """Подключающийся игрок."""
    name = Field(1)
    """Ник при подключении."""
    ip = Field(2)
    """IP-адрес без порта."""

    def reject(self, reason: str = "Rejected") -> None:
        """Не пускать игрока; ``reason`` он увидит при отключении."""
        self.result = reason


class PutInServer(Event):
    """Игрок вошёл в игру: можно писать ему в чат, показывать меню и HUD.

    #### Поля
    - `player: Player` — игрок, который вошёл в игру

    #### Пример
    ```python
    @plugin.on(events.PutInServer)
    async def greet(e: events.PutInServer) -> None:
        player = e.player  # событие живёт до первого await
        await sleep(3)
        player.print(f"!gПривет, !t{player.name}")
    ```
    """

    cancellable = False
    scope = "player"
    player = Field(0, "player")
    """Игрок, который вошёл в игру."""


class Authorized(Event):
    """SteamID игрока известен: место для загрузки его данных из базы.

    #### Поля
    - `player: Player` — игрок, чей SteamID стал известен
    - `steam_id: str` — SteamID: ``STEAM_0:1:123``

    #### Пример
    ```python
    @plugin.on(events.Authorized)
    async def load(e: events.Authorized) -> None:
        player = e.player
        stats[player] = await table.get(player.steam_id)
    ```
    """

    cancellable = False
    scope = "player"
    player = Field(0, "player")
    """Игрок, чей SteamID стал известен."""
    steam_id = Field(1)
    """SteamID: ``STEAM_0:1:123``."""


class Disconnected(Event):
    """Игрок вышел. Данные ``PlayerState`` и задачи игрока удаляются сами после обработчиков.

    #### Поля
    - `player: Player` — вышедший игрок; после обработчиков хэндл недействителен
    """

    cancellable = False
    player = Field(0, "player")
    """Вышедший игрок; после обработчиков хэндл недействителен."""


class Say(Event):
    """Сообщение в чат (say и say_team); ``e.cancel()`` — скрыть его.

    Для команд вида ``/hp`` удобнее ``@plugin.command("/hp")``.

    #### Поля
    - `player: Player` — кто пишет
    - `text: str` — текст сообщения без кавычек
    - `team: bool` — True — say_team (чат команды)

    #### Пример
    ```python
    @plugin.on(events.Say)
    def no_ads(e: events.Say) -> None:
        if "http" in e.text:
            e.cancel()
    ```
    """

    scope = "player"
    player = Field(0, "player")
    """Кто пишет."""
    text = Field(1)
    """Текст сообщения без кавычек."""
    team = Field(2, "bool", doc="True — say_team")
    """True — say_team (чат команды)."""


# --- игра (хуки C++-модуля; нужен ReGameDLL) ---


class PlayerSpawn(Event):
    """Игрок возрождается (pre и post, нужен ReGameDLL).

    В post оружие и здоровье уже выданы — бонусы ставьте там.

    #### Поля
    - `player: Player` — возрождающийся игрок

    #### Пример
    ```python
    @plugin.on(events.PlayerSpawn, post=True)
    def bonus(e: events.PlayerSpawn) -> None:
        e.player.armor = 100
    ```
    """

    hook = "player_spawn"
    phases = (False, True)
    scope = "player"
    player = Field(0, "player")
    """Возрождающийся игрок."""


class TakeDamage(Event):
    """Игрок получает урон (pre и post, нужен ReGameDLL).

    В pre можно изменить ``damage`` и ``damage_type`` или отменить урон
    целиком через ``e.cancel()``.

    #### Поля
    - `victim: Player` — кто получает урон
    - `inflictor: Player | Entity | None` — чем нанесён урон: игрок, граната или другая сущность
    - `attacker: Player | None` — кто нанёс урон; None — урон от мира (падение, trigger_hurt)
    - `damage: float` — урон; в pre можно менять: ``e.damage *= 2``
    - `damage_type: int` — Биты DMG_* (DMG_FALL, DMG_BULLET...); в pre можно менять

    #### Пример
    ```python
    @plugin.on(events.TakeDamage)
    def no_team_damage(e: events.TakeDamage) -> None:
        if e.attacker is not None and e.attacker.is_teammate(e.victim):
            e.cancel()
    ```
    """

    hook = "take_damage"
    phases = (False, True)
    has_result = True
    victim = Field(0, "player")
    """Кто получает урон."""
    inflictor = Field(1, "entity")
    """Чем нанесён урон: игрок, граната или другая сущность."""
    attacker = Field(2, "player?", doc="None — урон от мира (падение, trigger_hurt)")
    """Кто нанёс урон; None — урон от мира (падение, trigger_hurt)."""
    damage = Field(3, "float", mutable=True)
    """Урон; в pre можно менять: ``e.damage *= 2``."""
    damage_type = Field(4, "int", mutable=True)
    """Биты DMG_* (DMG_FALL, DMG_BULLET...); в pre можно менять."""


class PlayerKilled(Event):
    """Игрок убит (pre и post, нужен ReGameDLL).

    #### Поля
    - `victim: Player` — убитый игрок
    - `killer: Player | None` — убийца; None — убил мир
    - `headshot: bool` — убийство в голову
    - `weapon: str` — оружие без префикса weapon_: ``ak47``, ``knife``, ``grenade``

    #### Пример
    ```python
    @plugin.on(events.PlayerKilled, post=True)
    def headshot_bonus(e: events.PlayerKilled) -> None:
        if e.killer is not None and e.headshot:
            e.killer.money += 300
    ```
    """

    hook = "player_killed"
    phases = (False, True)
    victim = Field(0, "player")
    """Убитый игрок."""
    killer = Field(1, "player?", doc="None — убил мир")
    """Убийца; None — убил мир."""
    headshot = Field(2, "bool")
    """Убийство в голову."""
    weapon = Field(3, doc="имя оружия без префикса weapon_")
    """Оружие без префикса weapon_: ``ak47``, ``knife``, ``grenade``."""


class RoundStart(Event):
    """Начался новый раунд — начало freezetime (RestartRound ReGameDLL)."""

    hook = "round_start"
    phases = (True,)
    cancellable = False


class RoundEnd(Event):
    """Раунд завершается (pre и post, нужен ReGameDLL).

    В pre можно отменить конец раунда или изменить ``delay`` до следующего.

    #### Поля
    - `winner: Winner` — кто победил: ``Winner.T``, ``Winner.CT``, ``Winner.DRAW``
    - `reason: int` — причина конца раунда (ScenarioEventEndRound ReGameDLL)
    - `delay: float` — секунд до следующего раунда; в pre можно менять

    #### Пример
    ```python
    @plugin.on(events.RoundEnd, post=True)
    def announce(e: events.RoundEnd) -> None:
        if e.winner == Winner.CT:
            server.print("!tКонтр-террористы!y победили")
    ```
    """

    hook = "round_end"
    phases = (False, True)
    winner = Field(0, "winner")
    """Кто победил: ``Winner.T``, ``Winner.CT``, ``Winner.DRAW``."""
    reason = Field(1, "int")
    """Причина конца раунда (ScenarioEventEndRound ReGameDLL)."""
    delay = Field(2, "float", mutable=True)
    """Секунд до следующего раунда; в pre можно менять."""



class TeamSelect(Event):
    """Игрок выбирает команду в меню (pre и post, нужен ReGameDLL).

    ``e.cancel()`` — не пускать в команду; ``e.slot`` можно заменить в pre.

    #### Поля
    - `player: Player` — кто выбирает
    - `slot: int` — пункт меню: 1 — T, 2 — CT, 5 — авто, 6 — зрители; в pre можно менять

    #### Пример
    ```python
    @plugin.on(events.TeamSelect)
    def no_spectators(e: events.TeamSelect) -> None:
        if e.slot == 6 and not e.player.has_access(Access.KICK):
            e.player.print("!tЗрителями могут быть только админы")
            e.cancel()
    ```
    """

    hook = "team_select"
    phases = (False, True)
    scope = "player"
    player = Field(0, "player")
    """Кто выбирает команду."""
    slot = Field(1, "int", mutable=True)
    """Пункт меню: 1 — T, 2 — CT, 5 — авто, 6 — зрители; в pre можно менять."""

    @property
    def team(self) -> Team | None:
        """Выбранная команда; None — автовыбор."""
        return {1: Team.T, 2: Team.CT, 6: Team.SPECTATOR}.get(self.slot)


class MoneyChange(Event):
    """Деньги игрока меняются (pre и post, нужен ReGameDLL).

    В pre можно изменить ``amount`` или отменить начисление.

    #### Поля
    - `player: Player` — чьи деньги
    - `amount: int` — на сколько: плюс — начисление, минус — трата; в pre можно менять
    - `reason: MoneyReason` — за что: убийство, бонус раунда, покупка...
    - `track: bool` — True — игрок увидит изменение на экране

    #### Пример
    ```python
    @plugin.on(events.MoneyChange)
    def double_kill_reward(e: events.MoneyChange) -> None:
        if e.reason == MoneyReason.ENEMY_KILLED:
            e.amount *= 2
    ```
    """

    hook = "money_change"
    phases = (False, True)
    scope = "player"
    player = Field(0, "player")
    """Чьи деньги меняются."""
    amount = Field(1, "int", mutable=True)
    """На сколько: плюс — начисление, минус — трата; в pre можно менять."""
    reason = Field(2, "money_reason")
    """За что: ``MoneyReason.ENEMY_KILLED``, ``MoneyReason.ROUND_BONUS``..."""
    track = Field(3, "bool")
    """True — игрок увидит изменение суммы на экране."""


class BuyWeapon(Event):
    """Игрок покупает оружие (pre и post, нужен ReGameDLL).

    ``e.cancel()`` в pre — покупка не состоится, деньги не спишутся.

    #### Поля
    - `player: Player` — покупатель
    - `weapon: str` — оружие без префикса weapon_: `ak47`, `awp`, `shield`

    #### Пример
    ```python
    @plugin.on(events.BuyWeapon)
    def no_awp(e: events.BuyWeapon) -> None:
        if e.weapon == "awp":
            e.player.print("!tAWP на сервере запрещена")
            e.cancel()
    ```
    """

    hook = "buy_weapon"
    phases = (False, True)
    scope = "player"
    player = Field(0, "player")
    """Покупатель."""
    weapon = Field(1)
    """Оружие без префикса weapon_: ``ak47``, ``awp``, ``shield``."""


class DropItem(Event):
    """Игрок выбрасывает предмет (pre и post, нужен ReGameDLL).

    ``e.cancel()`` в pre — предмет останется у игрока.

    #### Поля
    - `player: Player` — кто выбрасывает
    - `item: str` — предмет без префикса weapon_: `ak47`, `c4`
    - `box: Player | Entity | None` — выпавший weaponbox (только в post)

    #### Пример
    ```python
    @plugin.on(events.DropItem)
    def keep_bomb(e: events.DropItem) -> None:
        if e.item == "c4":
            e.cancel()
    ```
    """

    hook = "drop_item"
    phases = (False, True)
    scope = "player"
    player = Field(0, "player")
    """Кто выбрасывает."""
    item = Field(1)
    """Предмет без префикса weapon_: ``ak47``, ``c4``."""
    box = Field(2, "entity")
    """Выпавший weaponbox (только в post)."""


class NameChange(Event):
    """Игрок меняет ник (pre и post, нужен ReGameDLL).

    ``e.cancel()`` в pre — останется старый ник.

    Мёртвому игроку игра меняет ник только при следующем спавне: pre приходит
    дважды — при запросе и при самой смене, post — один раз, когда ник сменился.

    #### Поля
    - `player: Player` — кто меняет ник
    - `old: str` — прежний ник
    - `new: str` — новый ник

    #### Пример
    ```python
    @plugin.on(events.NameChange)
    def no_rename_dead(e: events.NameChange) -> None:
        if not e.player.alive:
            e.cancel()
    ```
    """

    hook = "name_change"
    phases = (False, True)
    scope = "player"
    player = Field(0, "player")
    """Кто меняет ник."""
    old = Field(1)
    """Прежний ник."""
    new = Field(2)
    """Новый ник."""


class FreezeEnd(Event):
    """Закончился freezetime: игроки могут двигаться и стрелять (нужен ReGameDLL).

    #### Пример
    ```python
    @plugin.on(events.FreezeEnd)
    def go(e: events.FreezeEnd) -> None:
        banner.show_all("Вперёд!")
    ```
    """

    hook = "freeze_end"
    phases = (True,)
    cancellable = False


class GrenadeThrow(Event):
    """Игрок бросил гранату (нужен ReGameDLL 5.5+).

    #### Поля
    - `player: Player` — кто бросил
    - `grenade: Player | Entity | None` — сущность летящей гранаты
    - `weapon: str` — `hegrenade`, `flashbang` или `smokegrenade`

    #### Пример
    ```python
    @plugin.on(events.GrenadeThrow)
    def announce(e: events.GrenadeThrow) -> None:
        if e.weapon == "hegrenade":
            server.print(f"!t{e.player.name}!y бросил гранату")
    ```
    """

    hook = "grenade_throw"
    phases = (True,)
    cancellable = False
    player = Field(0, "player")
    """Кто бросил."""
    grenade = Field(1, "entity")
    """Сущность летящей гранаты."""
    weapon = Field(2)
    """``hegrenade``, ``flashbang`` или ``smokegrenade``."""


class BombPlanted(Event):
    """Бомба заложена (нужен ReGameDLL 5.5+).

    #### Поля
    - `player: Player | None` — кто заложил
    - `bomb: Player | Entity | None` — сущность бомбы

    #### Пример
    ```python
    @plugin.on(events.BombPlanted)
    def planted(e: events.BombPlanted) -> None:
        banner.show_all("Бомба заложена!")
    ```
    """

    hook = "bomb_planted"
    phases = (True,)
    cancellable = False
    player = Field(0, "player?")
    """Кто заложил."""
    bomb = Field(1, "entity")
    """Сущность бомбы."""


class BombDefuseStart(Event):
    """Игрок начинает разминировать бомбу (pre и post, нужен ReGameDLL 5.5+).

    ``e.cancel()`` в pre — разминирование не начнётся.

    #### Поля
    - `player: Player` — сапёр
    - `bomb: Player | Entity | None` — сущность бомбы
    - `kit: bool` — с набором сапёра (5 секунд вместо 10)

    #### Пример
    ```python
    @plugin.on(events.BombDefuseStart, post=True)
    def defusing(e: events.BombDefuseStart) -> None:
        server.print(f"!t{e.player.name}!y разминирует{' с набором' if e.kit else ''}")
    ```
    """

    hook = "bomb_defuse_start"
    phases = (False, True)
    scope = "player"
    player = Field(0, "player")
    """Сапёр."""
    bomb = Field(1, "entity")
    """Сущность бомбы."""
    kit = Field(2, "bool")
    """С набором сапёра (5 секунд вместо 10)."""


class BombDefuseEnd(Event):
    """Разминирование закончилось: успешно или прервано (нужен ReGameDLL 5.5+).

    #### Поля
    - `player: Player | None` — сапёр
    - `bomb: Player | Entity | None` — сущность бомбы
    - `defused: bool` — True — бомба обезврежена, False — сапёр отпустил «E» или погиб

    #### Пример
    ```python
    @plugin.on(events.BombDefuseEnd)
    def defused(e: events.BombDefuseEnd) -> None:
        if e.defused and e.player is not None:
            e.player.money += 500
    ```
    """

    hook = "bomb_defuse_end"
    phases = (True,)
    cancellable = False
    player = Field(0, "player?")
    """Сапёр."""
    bomb = Field(1, "entity")
    """Сущность бомбы."""
    defused = Field(2, "bool")
    """True — бомба обезврежена, False — разминирование прервано."""


class BombExploded(Event):
    """Бомба взорвалась (нужен ReGameDLL 5.5+).

    #### Поля
    - `player: Player | None` — кто заложил (None — уже вышел)
    - `bomb: Player | Entity | None` — сущность бомбы

    #### Пример
    ```python
    @plugin.on(events.BombExploded)
    def boom(e: events.BombExploded) -> None:
        if e.player is not None:
            e.player.money += 300
    ```
    """

    hook = "bomb_exploded"
    phases = (True,)
    cancellable = False
    player = Field(0, "player?")
    """Кто заложил бомбу."""
    bomb = Field(1, "entity")
    """Сущность бомбы (в момент взрыва ещё существует)."""

def _collect(base: type[Event]) -> dict[str, type[Event]]:
    out: dict[str, type[Event]] = {}
    for cls in base.__subclasses__():
        out[cls.__name__] = cls
        out.update(_collect(cls))
    return out


CATALOG: dict[str, type[Event]] = _collect(Event)
HOOKS: dict[str, type[Event]] = {cls.hook: cls for cls in CATALOG.values() if cls.hook}

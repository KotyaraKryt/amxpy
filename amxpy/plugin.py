"""Plugin и Router: объявления обработчиков, команд, нативов и форвардов.

Router собирает объявления в модуле, Plugin — корень плагина:
```python
plugin = Plugin("VIP", version="1.2.0", author="you")
plugin.include(cfg, api.router, perks.router)
```

Декораторы только записывают объявления; регистрирует их хост при загрузке,
поэтому код модулей можно импортировать без сервера (так делает компилятор).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import typing
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Concatenate, Generic, ParamSpec, Protocol, TypeVar, TypeVarTuple, overload

from . import _state, context
from .config import Config
from .events import Event
from .player import Access, Player

F = TypeVar("F", bound=Callable[..., Any])
E = TypeVar("E", bound=Event)
C = TypeVar("C", bound="Router | Config")
R = TypeVar("R")
P = ParamSpec("P")
Ts = TypeVarTuple("Ts")


# Типы, которые возвращают декораторы: в подсказках редактора вместо вложенных Callable
class HandlerDecorator(Protocol, Generic[E]):
    """Декоратор обработчика: функция принимает событие ``E``."""

    def __call__(self, fn: Callable[[E], R], /) -> Callable[[E], R]: ...


class CommandDecorator(Protocol):
    """Декоратор команды: первый параметр функции — игрок."""

    def __call__(self, fn: Callable[Concatenate[Player, P], R], /) -> Callable[Concatenate[Player, P], R]: ...


class TaskDecorator(Protocol):
    """Декоратор периодической задачи: функция без параметров."""

    def __call__(self, fn: Callable[[], R], /) -> Callable[[], R]: ...


class Decorator(Protocol):
    """Декоратор, который регистрирует функцию и возвращает её же."""

    def __call__(self, fn: F, /) -> F: ...

TYPE_CODES: dict[Any, str] = {int: "i", float: "f", bool: "b", str: "s", Player: "p"}
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
CHAT_COMMAND_RE = re.compile(r"^[/!]\S+$")
CONSOLE_COMMAND_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")


def type_code(tp: Any, *, result: bool = False) -> str:
    """Код типа для границы с Pawn (см. :mod:`amxpy._backend`)."""
    if result and tp in (None, type(None)):
        return "v"
    try:
        return TYPE_CODES[tp]
    except (KeyError, TypeError):
        raise TypeError(f"type {tp!r} cannot cross into Pawn (use int, float, bool, str or Player)") from None


@dataclass(eq=False)
class HandlerSpec:
    event: type[Event]
    fn: Callable[..., Any]
    post: bool
    priority: int
    filters: dict[str, Any]


@dataclass(eq=False)
class CommandSpec:
    names: tuple[str, ...]
    fn: Callable[..., Any]
    access: int
    help: str
    cooldown: float
    hide: bool


@dataclass(eq=False)
class ServerCommandSpec:
    name: str
    fn: Callable[..., Any]
    help: str


@dataclass(eq=False)
class NativeSpec:
    name: str
    fn: Callable[..., Any]
    params: list[tuple[str, str]]
    returns: str
    doc: str

    @property
    def codes(self) -> str:
        return "".join(code for _, code in self.params)


@dataclass(eq=False)
class PeriodicSpec:
    fn: Callable[[], Any]
    seconds: float
    delay: float


def native_spec(fn: Callable[..., Any], name: str) -> NativeSpec:
    if not NAME_RE.match(name):
        raise ValueError(f"invalid native name: {name!r}")
    if inspect.iscoroutinefunction(fn):
        raise TypeError(f"native {name} cannot be async")
    hints = typing.get_type_hints(fn)
    params: list[tuple[str, str]] = []
    for p in inspect.signature(fn).parameters.values():
        if p.kind not in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            raise TypeError(f"native {name}: only positional parameters are supported")
        if p.name not in hints:
            raise TypeError(f"native {name}: parameter {p.name!r} needs a type annotation")
        params.append((p.name, type_code(hints[p.name])))
    returns = type_code(hints.get("return"), result=True)
    return NativeSpec(name, fn, params, returns, inspect.getdoc(fn) or "")


class Forward:
    """Форвард — событие плагина для Pawn- и Python-подписчиков.

    Объявляется через :meth:`Router.forward`; в сгенерированном .inc появляется
    ``forward <имя>(...)``, Pawn-плагины ловят его обычной public-функцией,
    Python-плагины — :meth:`Router.on_forward`.

    #### Пример
    ```python
    granted = plugin.forward("vip_granted", player=Player, days=int)
    granted.emit(player, 30)
    ```
    """

    def __init__(self, name: str, params: list[tuple[str, str]]) -> None:
        if not NAME_RE.match(name):
            raise ValueError(f"invalid forward name: {name!r}")
        self.name = name
        self.params = params

    @property
    def codes(self) -> str:
        return "".join(code for _, code in self.params)

    def emit(self, *args: Any) -> int:
        """Разослать форвард всем подписчикам.

        #### Параметры
        - `*args` — значения в порядке объявления параметров.

        #### Возвращает
        Результат ExecuteForward: что вернули Pawn-обработчики (0, если их нет).

        #### Исключения
        - `TypeError` — число аргументов не совпадает с объявлением.
        """
        if len(args) != len(self.params):
            raise TypeError(f"forward {self.name} takes {len(self.params)} arguments, got {len(args)}")
        return _state.current().emit_forward(self, args)

    def __repr__(self) -> str:
        return f"<Forward {self.name}({', '.join(n for n, _ in self.params)})>"


class Router:
    """Набор объявлений модуля: обработчики, команды, нативы, форварды, задачи.

    Большой плагин делится на модули: в каждом свой ``Router()``, а корневой
    :class:`Plugin` подключает их через :meth:`include`. Декораторы только
    записывают объявления — регистрирует их рантайм при загрузке плагина.

    #### Пример
    ```python
    router = Router()

    @router.command("/hp")
    def hp(player: Player) -> None:
        player.print(f"HP: {player.health}")
    ```
    """

    def __init__(self) -> None:
        self._handlers: list[HandlerSpec] = []
        self._commands: list[CommandSpec] = []
        self._server_commands: list[ServerCommandSpec] = []
        self._natives: list[NativeSpec] = []
        self._forwards: list[Forward] = []
        self._subscriptions: list[tuple[str, Callable[..., Any]]] = []
        self._periodic: list[PeriodicSpec] = []
        self._components: list[Router | Config] = []

    # --- объявления ---
    def on(
        self, event: type[E], *, post: bool | None = None, priority: int = 0, **filters: Any
    ) -> HandlerDecorator[E]:
        """Обработчик события.

        В pre-фазе (по умолчанию) обработчик может менять изменяемые поля,
        отменить действие игры через ``e.cancel()`` или вернуть значение — ответ
        за игру. В post-фазе событие уже случилось: только чтение. Async-обработчик
        видит событие до первого ``await`` — нужные поля скопируйте заранее.

        #### Параметры
        - `event` — класс события из ``amxpy.events``.
        - `post` — ``True`` — после действия игры, ``False`` — до; по умолчанию — первая фаза события
          (pre, а у событий только с post-фазой, как ``FreezeEnd``, — post).
        - `priority` — больше — раньше среди обработчиков этого события.
        - `**filters` — ``поле=значение`` — вызывать только при совпадении поля.

        #### Исключения
        - `TypeError` — у события нет такой фазы или полей для фильтра.

        #### Пример
        ```python
        @plugin.on(events.TakeDamage)
        def double(e: events.TakeDamage) -> None:
            if e.attacker in vips:
                e.damage *= 2

        @plugin.on(events.Say, team=True)  # только say_team
        def team_chat(e: events.Say) -> None: ...
        ```
        """
        if not (isinstance(event, type) and issubclass(event, Event)) or event is Event:
            raise TypeError(f"expected an event class from amxpy.events, got {event!r}")
        if post is None:
            post = event.phases[0]
        if post not in event.phases:
            raise TypeError(f"{event.__name__} has no {'post' if post else 'pre'} phase")
        phase = post
        unknown = set(filters) - set(event.fields())
        if unknown:
            raise TypeError(f"{event.__name__} has no fields {sorted(unknown)} to filter on")

        def deco(fn: Callable[[E], R]) -> Callable[[E], R]:
            self._handlers.append(HandlerSpec(event, fn, phase, priority, filters))
            return fn

        return deco

    def command(
        self,
        *names: str,
        access: Access | int = Access.NONE,
        help: str = "",
        cooldown: float = 0.0,
        hide: bool = True,
    ) -> CommandDecorator:
        """Команда игрока: ``/name`` или ``!name`` — в чате, иначе — в консоли.

        Первый параметр обработчика — игрок, вызвавший команду. Остальные
        аргументы разбираются по аннотациям: ``str``, ``int``, ``float``, ``bool``,
        ``Player`` (по нику, ``#userid`` или SteamID), ``Enum``, ``Literal[...]``,
        ``X | None``; ``*rest: str`` забирает остаток строки. Usage и сообщения
        об ошибках строятся сами: ``amx_heal <target> [amount]``.

        #### Параметры
        - `*names` — имена команды; несколько — синонимы (``"/hp", "!hp"``).
        - `access` — нужные флаги доступа; без них игрок получит отказ.
        - `help` — описание для списка команд.
        - `cooldown` — секунд между вызовами одним игроком.
        - `hide` — не показывать чат-команду в чате.

        #### Пример
        ```python
        @plugin.command("amx_heal", access=Access.SLAY, help="Вылечить игрока")
        def heal(admin: Player, target: Player, amount: int = 100) -> None:
            target.health = min(target.health + amount, 255)
        ```
        """
        if not names:
            raise TypeError("command() needs at least one name")
        for name in names:
            if not (CHAT_COMMAND_RE.match(name) or CONSOLE_COMMAND_RE.match(name)):
                raise ValueError(f"invalid command name: {name!r}")

        def deco(fn: Callable[Concatenate[Player, P], R]) -> Callable[Concatenate[Player, P], R]:
            self._commands.append(CommandSpec(tuple(names), fn, int(access), help, float(cooldown), hide))
            return fn

        return deco

    def server_command(self, name: str, *, help: str = "") -> Decorator:
        """Команда серверной консоли и rcon (без игрока).

        Аргументы разбираются по аннотациям, как у :meth:`command`.

        #### Пример
        ```python
        @plugin.server_command("amx_vip_reload", help="Перечитать VIP из базы")
        async def reload_vips() -> None: ...
        ```
        """
        if not CONSOLE_COMMAND_RE.match(name):
            raise ValueError(f"invalid server command name: {name!r}")

        def deco(fn: F) -> F:
            self._server_commands.append(ServerCommandSpec(name, fn, help))
            return fn

        return deco

    @overload
    def native(self, fn: F, /) -> F: ...
    @overload
    def native(self, fn: str | None = None, /, *, name: str | None = None) -> Decorator: ...
    def native(self, fn: Callable[..., Any] | str | None = None, /, *, name: str | None = None) -> Any:
        """Натив для Pawn-плагинов; сигнатура берётся из аннотаций.

        Типы параметров: ``int``, ``float``, ``bool``, ``str``, ``Player``; результат —
        они же или ``None``. Натив попадает в сгенерированный ``<плагин>.inc``
        вместе с docstring; новый натив или смена сигнатуры доступны Pawn после
        рестарта сервера. Натив не может быть async: Pawn ждёт ответ сразу.

        #### Пример
        ```python
        @plugin.native
        def vip_is_user_vip(player: Player) -> bool:
            return player in vips

        @plugin.native("vip_days")  # имя для Pawn отличается от имени функции
        def days_left(player: Player) -> int: ...
        ```
        """

        def register(f: F) -> F:
            self._natives.append(native_spec(f, name or f.__name__))
            return f

        if callable(fn):
            return register(fn)
        if isinstance(fn, str):
            name = fn
        return register

    def forward(self, name: str, *types: type, **named: type) -> Forward:
        """Объявить форвард для Pawn- и Python-подписчиков.

        #### Параметры
        - `name` — имя форварда (латиница, как в Pawn).
        - `*types` — типы безымянных параметров (``arg1``, ``arg2``...).
        - `**named` — именованные параметры: ``имя=тип``.

        #### Возвращает
        :class:`Forward`; разослать — ``.emit(...)``.

        #### Пример
        ```python
        granted = plugin.forward("vip_granted", player=Player, days=int)
        ...
        granted.emit(player, 30)
        ```
        """
        params = [(f"arg{i}", type_code(t)) for i, t in enumerate(types, 1)]
        params += [(n, type_code(t)) for n, t in named.items()]
        fwd = Forward(name, params)
        self._forwards.append(fwd)
        return fwd

    def on_forward(self, name: str) -> Decorator:
        """Подписка на форвард по имени: Python-плагина, Pawn-плагина или самого AMXX.

        Форварды Pawn (``CreateMultiForward`` + ``ExecuteForward``) и форварды ядра
        (``client_putinserver``...) доходят через плагин-приёмник ``amxpy_forwards.amxx``,
        который AMXX загружает с каждой картой: новая подписка начинает работать со
        следующей карты. Аргументы разбираются по аннотациям: ``int``, ``bool``,
        ``float``, ``str``, ``Player``; ``amxx.Ref``/``amxx.FloatRef`` — параметр по
        ссылке, его ``.value`` вернётся в Pawn. Без аннотации — число.
        Возвращённое число — ответ форварда (``PLUGIN_HANDLED`` = 1); из нескольких
        подписчиков берётся наибольший.

        #### Пример
        ```python
        @plugin.on_forward("jb_day_start")          # форвард Pawn-мода
        def day_start(day: int, title: str) -> None:
            server.print(f"!gДень {day}: !t{title}")

        @plugin.on_forward("vip_granted")           # форвард Python-плагина
        def on_vip(player: Player, days: int) -> None: ...
        ```
        """

        def deco(fn: F) -> F:
            self._subscriptions.append((name, fn))
            return fn

        return deco

    def every(self, seconds: float, *, delay: float | None = None) -> TaskDecorator:
        """Периодическая задача, пока плагин работает; может быть async.

        #### Параметры
        - `seconds` — период в секундах.
        - `delay` — задержка перед первым запуском (по умолчанию — один период).

        #### Пример
        ```python
        @plugin.every(60)
        def advert() -> None:
            server.print("!gСайт сервера: !texample.com")
        ```
        """
        if seconds <= 0:
            raise ValueError("every(): period must be positive")

        def deco(fn: Callable[[], R]) -> Callable[[], R]:
            self._periodic.append(PeriodicSpec(fn, float(seconds), float(seconds if delay is None else delay)))
            return fn

        return deco

    @overload
    def include(self) -> None: ...
    @overload
    def include(self, first: C, /, *rest: Router | Config) -> C: ...
    def include(self, *components: Router | Config) -> Any:
        """Подключить роутеры модулей и конфиги; возвращает первый компонент.

        #### Пример
        ```python
        cfg = plugin.include(Settings(), perks.router, api.router)
        cfg.hp_bonus  # тип cvar'а известен редактору
        ```
        """
        for component in components:
            if not isinstance(component, (Router, Config)):
                raise TypeError(f"include() accepts Router and Config, got {component!r}")
        self._components.extend(components)
        return components[0] if components else None

    # --- во время работы ---
    def spawn(self, coro: Coroutine[Any, Any, R]) -> asyncio.Task[R]:
        """Запустить фоновую задачу плагина.

        Задача отменяется при выгрузке или перезагрузке плагина; запущенная из
        обработчика игрока — ещё и при его выходе.

        #### Пример
        ```python
        plugin.spawn(countdown(player))
        ```
        """
        return _state.current().spawn(coro)

    async def offload(self, fn: Callable[[*Ts], R], *args: *Ts) -> R:
        """Выполнить блокирующую функцию в потоке, не задерживая кадр сервера.

        #### Пример
        ```python
        data = await plugin.offload(requests.get, "https://example.com/api")
        ```
        """
        return await _state.current().offload(fn, *args)

    async def wait_for(
        self, event: type[E], *, check: Callable[[E], bool] | None = None, timeout: float | None = None
    ) -> E:
        """Дождаться события и вернуть копию его полей.

        #### Параметры
        - `event` — класс события.
        - `check` — условие; событие без совпадения пропускается.
        - `timeout` — секунд ожидания; по истечении — ``TimeoutError``.

        #### Возвращает
        Копия полей события (методы вроде ``cancel()`` у копии не работают).

        #### Пример
        ```python
        e = await plugin.wait_for(events.Say, check=lambda e: e.player is player, timeout=30)
        player.print(f"Вы написали: {e.text}")
        ```
        """
        return await _state.current().wait_for(event, check=check, timeout=timeout)

    @property
    def log(self) -> logging.Logger:
        """Логгер плагина: ``plugin.log.info("...")`` пишет в лог сервера с именем плагина."""
        inst = context.instance()
        return logging.getLogger(f"amxpy.{inst.name if inst else 'plugin'}")


class Plugin(Router):
    """Корень плагина: название, версия, автор и все объявления.

    В пакете плагина создаётся ровно один ``Plugin(...)``; другие модули
    объявляют обработчики в своих :class:`Router` и подключаются через
    :meth:`include`.

    #### Параметры
    - `name` — название в ``amxpy list`` и логах.
    - `version` — версия плагина.
    - `author` — автор.
    - `description` — краткое описание.
    - `url` — страница плагина.

    #### Пример
    ```python
    plugin = Plugin("VIP", version="1.2.0", author="you")
    cfg = plugin.include(Settings(), perks.router)
    ```
    """

    def __init__(self, name: str, *, version: str = "0.0.0", author: str = "", description: str = "", url: str = ""):
        super().__init__()
        self.name = name
        self.version = version
        self.author = author
        self.description = description
        self.url = url
        self._instance = context.instance()
        if self._instance is not None:
            self._instance.attach_plugin(self)

    def __repr__(self) -> str:
        return f"<Plugin {self.name} {self.version}>"

    def _inst(self) -> Any:
        if self._instance is None:
            raise RuntimeError("the plugin is not loaded by the amxpy runtime")
        return self._instance

    @property
    def log(self) -> logging.Logger:
        """Логгер плагина: ``plugin.log.info("...")`` пишет в лог сервера с именем плагина."""
        return logging.getLogger(f"amxpy.{self._instance.name if self._instance else self.name}")

    def keep(self, key: str, value: Any) -> None:
        """Сохранить значение на время горячей перезагрузки (должно поддерживать pickle).

        Новая версия плагина получит его через :meth:`kept` — в том числе при импорте
        модуля. Вызывать можно в любой момент, в том числе в ``on_unload`` (в async-колбэке —
        до первого ``await``). Данные игроков проще хранить в ``PlayerState(keep=True)``.

        #### Пример
        ```python
        @plugin.on_unload
        def save() -> None:
            plugin.keep("round", current_round)
        ```
        """
        self._inst().kept[key] = value

    def kept(self, key: str, default: Any = None) -> Any:
        """Значение, сохранённое через :meth:`keep` предыдущей версией плагина.

        #### Пример
        ```python
        current_round = plugin.kept("round", 0)
        ```
        """
        return self._inst().restored.get(key, default)

    def config_file(self, name: str, default: str = "") -> Path:
        """Файл настроек плагина на сервере: ``addons/amxpy/configs/<плагин>/<name>``.

        Если файла нет, он создаётся с текстом ``default`` — общий отступ и первая пустая
        строка убираются. Существующий файл не перезаписывается никогда: ни при перезагрузке,
        ни при ``amxpy deploy`` — это файл владельца сервера. Формат любой, читайте его сами
        (``configparser``, ``tomllib``, ``json``), лучше в ``events.Init`` или ``events.MapStart``.

        #### Параметры
        - `name` — имя файла в папке плагина, можно с подпапкой: ``texts/ru.txt``.
        - `default` — содержимое нового файла.

        #### Возвращает
        Путь к файлу (``pathlib.Path``).

        #### Исключения
        - `ValueError` — путь выходит за папку плагина.

        #### Пример
        ```python
        path = plugin.config_file("adverts.ini", default='''
            [messages]
            1 = !gНаш сайт: !texample.com
        ''')

        @plugin.on(events.Init)
        def load(e: events.Init) -> None:
            ini = configparser.ConfigParser()
            ini.read(path, encoding="utf-8")
        ```
        """
        return self._inst().config_file(name, default)

    def on_unload(self, callback: Callable[[], Any]) -> Callable[[], Any]:
        """Вызвать при выгрузке и перезагрузке плагина; может быть async.

        #### Пример
        ```python
        @plugin.on_unload
        async def flush() -> None:
            await table.put(stats)
        ```
        """
        self._inst().unload_callbacks.append(callback)
        return callback

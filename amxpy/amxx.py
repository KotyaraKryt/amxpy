"""Нативы AMX Mod X, модулей (cstrike, fun, fakemeta, ReAPI...) и Pawn-плагинов из Python.

```python
from amxpy import amxx

amxx.call("cs_set_user_money", player, 16000)

name = amxx.String(32)
amxx.call("get_user_name", player, name, 31)
player.print(name.value)
```

Аргументы переводятся по типу: ``int``, ``bool``, ``Player``, ``Entity`` — число;
``float`` — ``Float:``; ``str`` — строка. Выходные параметры — обёртки:
``String(размер)`` — буфер под строку, ``Ref``/``FloatRef`` — параметр по ссылке
(``&x``), ``Array``/``FloatArray`` — массив, который натив может изменить.
В переменных аргументах (``any:...``, как у ``client_print``) числа передаются
по ссылке — оберните их в ``Ref``/``FloatRef``.

Нативы вызываются только в игровом потоке (не из ``offload()``). Натив, который
регистрирует колбэк вызывающего плагина (``set_task``, ``register_event``...), из
Python не работает — для этого есть свои средства amxpy.
"""

from __future__ import annotations

import struct
import threading
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from . import _state
from ._bridge import build_amxx
from .player import Entity, Player

if TYPE_CHECKING:
    from ._host import Host

__all__ = ["Array", "FloatArray", "FloatRef", "NativeError", "Ref", "String", "available", "call", "call_float"]


class NativeError(RuntimeError):
    """Натив недоступен или завершился с ошибкой (подробности — в логе ошибок AMXX)."""


class String:
    """Буфер под строку, которую запишет натив: ``String(32)`` → после вызова ``.value``."""

    def __init__(self, size: int = 256) -> None:
        if size <= 0:
            raise ValueError("String size must be positive")
        self.size = size
        self.value = ""

    def __repr__(self) -> str:
        return f"String({self.size}, value={self.value!r})"


class Ref:
    """Целое по ссылке (``&value`` в Pawn): натив читает и меняет ``.value``."""

    def __init__(self, value: int = 0) -> None:
        self.value = int(value)

    def __repr__(self) -> str:
        return f"Ref({self.value})"


class FloatRef:
    """``Float:`` по ссылке (``&Float:value``): натив читает и меняет ``.value``."""

    def __init__(self, value: float = 0.0) -> None:
        self.value = float(value)

    def __repr__(self) -> str:
        return f"FloatRef({self.value})"


class Array:
    """Массив целых, который натив может прочитать и изменить: ``Array(3)`` или ``Array([1, 2, 3])``."""

    def __init__(self, values: int | Iterable[int] = 0) -> None:
        self.values = [0] * values if isinstance(values, int) else [int(v) for v in values]

    def __repr__(self) -> str:
        return f"Array({self.values})"


class FloatArray:
    """Массив ``Float:`` (вектор, цвет...): ``FloatArray(3)`` → после вызова ``.values``."""

    def __init__(self, values: int | Iterable[float] = 0) -> None:
        self.values = [0.0] * values if isinstance(values, int) else [float(v) for v in values]

    def __repr__(self) -> str:
        return f"FloatArray({self.values})"


Arg = int | float | str | Player | Entity | String | Ref | FloatRef | Array | FloatArray | Sequence[int] | Sequence[float] | None


def _spec(arg: Arg) -> tuple[str, Any]:
    if arg is None:
        return ("i", 0)
    if isinstance(arg, (bool, int)):
        return ("i", int(arg))
    if isinstance(arg, float):
        return ("f", arg)
    if isinstance(arg, str):
        return ("s", arg)
    if isinstance(arg, Player):
        arg._backend()  # вышедший игрок — StaleHandleError, а не натив над чужим слотом
        return ("i", arg.index)
    if isinstance(arg, Entity):
        return ("i", arg.index)
    if isinstance(arg, String):
        return ("b", arg.size)
    if isinstance(arg, Ref):
        return ("r", arg.value)
    if isinstance(arg, FloatRef):
        return ("q", arg.value)
    if isinstance(arg, Array):
        return ("a", arg.values)
    if isinstance(arg, FloatArray):
        return ("v", arg.values)
    if isinstance(arg, (list, tuple)):
        if any(isinstance(v, float) for v in arg):
            return ("v", [float(v) for v in arg])
        return ("a", [int(v) for v in arg])
    raise TypeError(f"cannot pass {type(arg).__name__} to a native")


def _store(arg: Arg, value: Any) -> None:
    if isinstance(arg, (String, Ref, FloatRef)):
        arg.value = value
    elif isinstance(arg, (Array, FloatArray)):
        arg.values = list(value)


class Bridge:
    """Привязка нативов по имени через «мост» (см. :mod:`amxpy._bridge`); один на сервер."""

    def __init__(self, host: Host) -> None:
        self.host = host
        self.bound: dict[str, tuple[int, int, int]] = {}  # имя → (мост, номер в таблице, адрес)
        self.missing: set[str] = set()  # не нашлись; сбрасывается на смене карты
        self._loaded = 0

    def resolve(self, names: Iterable[str]) -> set[str]:
        """Привязать нативы; вернуть те, которых на сервере нет."""
        names = list(names)
        todo = [n for n in dict.fromkeys(names) if n not in self.bound and n not in self.missing]
        if todo:
            folder = self.host.base_dir / "data"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"amxpy-natives-{self._loaded}.amxx"
            self._loaded += 1
            path.write_bytes(build_amxx(todo))
            try:
                bridge, addresses, error = self.host.backend.load_bridge(str(path))
            finally:
                path.unlink(missing_ok=True)
            if bridge < 0:
                raise NativeError(f"AMX Mod X did not load the native bridge: {error}")
            for index, (name, address) in enumerate(zip(todo, addresses)):
                if address:
                    self.bound[name] = (bridge, index, address)
                else:
                    self.missing.add(name)
        return {n for n in names if n not in self.bound}

    def call(self, name: str, args: Sequence[Arg]) -> int:
        if threading.get_ident() != self.host.game_thread:
            raise NativeError(f"{name}: natives can be called only from the game thread, not from offload()")
        if name not in self.bound and self.resolve([name]):
            raise NativeError(f"native {name} is not available: is its module or plugin loaded?")
        bridge, index, address = self.bound[name]
        specs = [_spec(a) for a in args]
        result, outputs, error = self.host.backend.call_bridge(bridge, index, address, specs)
        if error:
            raise NativeError(f"{name} reported an error (AMX error {error}); the reason is in the AMX Mod X error log")
        produced = iter(outputs)
        for arg, (code, _) in zip(args, specs):
            if code in "brqav":
                _store(arg, next(produced))
        return int(result)


def call(name: str, *args: Arg) -> int:
    """Вызвать натив по имени и вернуть результат-ячейку.

    #### Параметры
    - `name` — имя натива: ``cs_set_user_money``, ``rg_give_item``, натив Pawn-плагина.
    - `*args` — аргументы по порядку объявления натива (см. описание модуля).

    #### Возвращает
    Результат натива как целое; для ``Float:``-результата — :func:`call_float`.

    #### Исключения
    - `NativeError` — натива нет на сервере или он завершился с ошибкой.

    #### Пример
    ```python
    amxx.call("cs_set_user_money", player, 16000)
    origin = amxx.Array(3)
    amxx.call("get_user_origin", player, origin)
    ```
    """
    return _state.current().amxx.call(name, args)


def call_float(name: str, *args: Arg) -> float:
    """Вызвать натив, который возвращает ``Float:``: ``amxx.call_float("entity_range", a, b)``."""
    return struct.unpack("<f", struct.pack("<i", call(name, *args)))[0]


def available(*names: str) -> bool:
    """Есть ли на сервере все эти нативы (заодно привязывает их заранее)."""
    return not _state.current().amxx.resolve(names)

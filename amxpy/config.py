"""Типизированные cvar'ы.

    class Settings(Config, prefix="vip_"):
        hp_bonus: int = cvar(25, "Доп. HP на спавне", min=0, max=155)

    cfg = Settings()   # cvar vip_hp_bonus; cfg.hp_bonus читает текущее значение

При загрузке плагина cvar'ы регистрируются, а файл
``addons/amxpy/configs/<плагин>.cfg`` создаётся (если его нет) и выполняется.
"""

from __future__ import annotations

import typing
from collections.abc import Callable
from typing import Any

from . import _state, context

FCVAR_ARCHIVE = 1
FCVAR_SERVER = 4
FCVAR_PROTECTED = 32
FCVAR_SPONLY = 64

_TYPES = (bool, int, float, str)
_FALSE = {"", "0", "false", "off", "no"}


class CvarSpec:
    """Описание одного cvar'а."""

    __slots__ = ("attr", "name", "type", "default", "description", "min", "max", "flags", "protected")

    def __init__(
        self,
        default: Any,
        description: str = "",
        *,
        min: float | None = None,
        max: float | None = None,
        flags: int = 0,
        protected: bool = False,
        name: str | None = None,
    ) -> None:
        self.attr = ""
        self.name = name or ""
        self.type: type = type(default)
        self.default = default
        self.description = description
        self.min = min
        self.max = max
        self.flags = flags
        self.protected = protected

    def coerce(self, value: Any) -> Any:
        value = self.type(value)
        if self.type in (int, float):
            if self.min is not None and value < self.min:
                value = self.type(self.min)
            if self.max is not None and value > self.max:
                value = self.type(self.max)
        return value

    def parse(self, raw: str | None) -> Any:
        if raw is None:
            return self.default
        try:
            if self.type is bool:
                return raw.strip().lower() not in _FALSE
            if self.type is int:
                return self.coerce(int(float(raw)))
            if self.type is float:
                return self.coerce(float(raw))
        except ValueError:
            return self.default
        return raw

    def to_str(self, value: Any) -> str:
        return format_value(self.type, value)

    def row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.__name__,
            "default": self.to_str(self.default),
            "description": self.description,
            "min": self.min,
            "max": self.max,
        }


def cvar(
    default: Any,
    description: str = "",
    *,
    min: float | None = None,
    max: float | None = None,
    flags: int = 0,
    protected: bool = False,
    name: str | None = None,
) -> Any:
    """Объявить cvar в классе :class:`Config`.

    Тип берётся из аннотации; cvar регистрируется при загрузке плагина, а в
    ``addons/amxpy/configs/<плагин>.cfg`` пишется значение по умолчанию с описанием.

    #### Параметры
    - `default` — значение по умолчанию (литерал: его читает компилятор).
    - `description` — комментарий в .cfg.
    - `min` — нижняя граница для чисел.
    - `max` — верхняя граница для чисел.
    - `flags` — флаги FCVAR_* движка.
    - `protected` — скрыть значение (FCVAR_PROTECTED), например для паролей.
    - `name` — имя cvar'а целиком вместо ``prefix + имя поля``.

    #### Пример
    ```python
    class Settings(Config, prefix="vip_"):
        hp_bonus: int = cvar(25, "Доп. HP на спавне", min=0, max=155)
        enabled: bool = cvar(True, "Включить плагин")
    ```
    """
    return CvarSpec(default, description, min=min, max=max, flags=flags, protected=protected, name=name)


class _CvarField:
    __slots__ = ("spec",)

    def __init__(self, spec: CvarSpec) -> None:
        self.spec = spec

    def __get__(self, cfg: Config | None, owner: type | None = None) -> Any:
        if cfg is None:
            return self.spec
        host = _state.host
        return self.spec.parse(host.backend.cvar_get(self.spec.name) if host is not None else None)

    def __set__(self, cfg: Config, value: Any) -> None:
        _state.current().backend.cvar_set(self.spec.name, self.spec.to_str(self.spec.coerce(value)))


class Config:
    """Группа cvar'ов плагина: ``class Settings(Config, prefix="vip_")``.

    Поля — cvar'ы: ``cfg.hp_bonus`` читает текущее значение с сервера,
    присваивание меняет cvar. Подключается через ``plugin.include(Settings())``.

    #### Параметры
    - `prefix` — начало имён cvar'ов (``vip_`` + ``hp_bonus`` = ``vip_hp_bonus``).

    #### Пример
    ```python
    class Settings(Config, prefix="vip_"):
        hp_bonus: int = cvar(25, "Доп. HP на спавне", min=0)

    cfg = plugin.include(Settings())
    player.health += cfg.hp_bonus
    ```
    """

    _prefix: typing.ClassVar[str] = ""
    _specs: typing.ClassVar[dict[str, CvarSpec]] = {}

    def __init_subclass__(cls, prefix: str = "", **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._prefix = prefix
        specs = dict(cls._specs)
        try:
            hints = typing.get_type_hints(cls)
        except Exception:
            hints = {}
        for attr, value in list(vars(cls).items()):
            if not isinstance(value, CvarSpec):
                continue
            value.attr = attr
            value.name = value.name or prefix + attr
            value.type = hints.get(attr, type(value.default))
            if value.type not in _TYPES:
                raise TypeError(f"{cls.__name__}.{attr}: cvar type must be bool, int, float or str")
            specs[attr] = value
            setattr(cls, attr, _CvarField(value))
        cls._specs = specs

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[[Any, Any], Any]]] = {}
        self._seen: dict[str, Any] = {}
        owner = context.instance()
        if owner is not None:
            owner.configs.append(self)

    @classmethod
    def specs(cls) -> list[CvarSpec]:
        """Описания всех cvar'ов группы."""
        return list(cls._specs.values())

    def on_change(self, attr: str) -> Callable[[Callable[[Any, Any], Any]], Callable[[Any, Any], Any]]:
        """Подписаться на изменение cvar'а; обработчик получает (старое, новое).

        #### Пример
        ```python
        @cfg.on_change("hp_bonus")
        def changed(old: int, new: int) -> None:
            plugin.log.info("hp_bonus: %s → %s", old, new)
        ```
        """
        if attr not in self._specs:
            raise AttributeError(f"{type(self).__name__} has no cvar {attr!r}")

        def deco(fn: Callable[[Any, Any], Any]) -> Callable[[Any, Any], Any]:
            self._listeners.setdefault(attr, []).append(fn)
            return fn

        return deco


def format_value(tp: type, value: Any) -> str:
    """Значение cvar'а строкой — одинаково в рантайме и в компиляторе."""
    if tp is bool:
        return "1" if value else "0"
    if tp is float:
        return format(float(value), "g")
    return str(value)


def render_cfg(title: str, rows: list[dict[str, Any]]) -> str:
    """Текст .cfg с описаниями и значениями по умолчанию."""
    out = [f"// {title}: cvars (generated by amxpy)", ""]
    for row in rows:
        if row.get("description"):
            out.append(f"// {row['description']}")
        lo, hi = row.get("min"), row.get("max")
        if lo is not None or hi is not None:
            out.append(f"// range: {'' if lo is None else lo}..{'' if hi is None else hi}")
        out.append(f'{row["name"]} "{row["default"]}"')
        out.append("")
    return "\n".join(out)

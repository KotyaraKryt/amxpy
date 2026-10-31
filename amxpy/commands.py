"""Команды: разбор аргументов по аннотациям обработчика.

    @plugin.command("amx_heal", access=Access.SLAY)
    def heal(admin: Player, target: Player, amount: int = 100) -> None: ...

Первый параметр — игрок, вызвавший команду. Остальные разбираются из
аргументов по аннотациям: str, int, float, bool, Player, Enum, Literal[...],
``X | None``; ``*rest: str`` забирает остаток строки. Usage строится сам:
``amx_heal <target> [amount]``.
"""

from __future__ import annotations

import enum
import inspect
import shlex
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Union, get_args, get_origin

from .player import Player

if TYPE_CHECKING:
    from ._host import Host

Converter = Callable[["Host", str, str], Any]  # (хост, имя параметра, токен) → значение


class ArgError(Exception):
    """Ошибка аргументов: ключ сообщения из :data:`amxpy.texts.MESSAGES` + параметры."""

    def __init__(self, key: str, **params: Any) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def tokenize(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:  # незакрытая кавычка
        return text.split()


@dataclass(frozen=True)
class Param:
    name: str
    convert: Converter
    default: Any
    required: bool
    variadic: bool


class Signature:
    """Разобранная сигнатура обработчика команды."""

    def __init__(self, fn: Callable[..., Any], *, with_caller: bool) -> None:
        hints = typing.get_type_hints(fn)
        params = list(inspect.signature(fn).parameters.values())
        if with_caller:
            if not params or params[0].kind not in (params[0].POSITIONAL_ONLY, params[0].POSITIONAL_OR_KEYWORD):
                raise TypeError(f"{fn.__qualname__}: the first parameter must be the calling player")
            params = params[1:]
        self.params: list[Param] = []
        for p in params:
            if p.kind in (p.KEYWORD_ONLY, p.VAR_KEYWORD):
                raise TypeError(f"{fn.__qualname__}: keyword-only parameters are not supported in commands")
            optional, ann = _unwrap_optional(hints.get(p.name, str))
            variadic = p.kind is p.VAR_POSITIONAL
            has_default = p.default is not p.empty
            self.params.append(
                Param(
                    name=p.name,
                    convert=_converter(ann),
                    default=p.default if has_default else None,
                    required=not (has_default or optional or variadic),
                    variadic=variadic,
                )
            )

    def usage(self, command: str) -> str:
        parts = [command]
        for p in self.params:
            if p.variadic:
                parts.append(f"[{p.name}...]")
            elif p.required:
                parts.append(f"<{p.name}>")
            else:
                parts.append(f"[{p.name}]")
        return " ".join(parts)

    def parse(self, host: Host, tokens: list[str]) -> list[Any]:
        values: list[Any] = []
        pos = 0
        for p in self.params:
            if p.variadic:
                values.extend(p.convert(host, p.name, t) for t in tokens[pos:])
                pos = len(tokens)
            elif pos < len(tokens):
                values.append(p.convert(host, p.name, tokens[pos]))
                pos += 1
            elif p.required:
                raise ArgError("usage")
            else:
                values.append(p.default)
        if pos < len(tokens):
            raise ArgError("usage")
        return values


_TRUE = {"1", "on", "yes", "true", "y", "да", "вкл"}
_FALSE = {"0", "off", "no", "false", "n", "нет", "выкл"}


def _unwrap_optional(ann: Any) -> tuple[bool, Any]:
    if get_origin(ann) in (Union, types.UnionType):
        args = get_args(ann)
        rest = [a for a in args if a is not type(None)]
        if len(rest) == 1 and len(args) == 2:
            return True, rest[0]
    return False, ann


def _converter(ann: Any) -> Converter:
    if ann in (str, Any, inspect.Parameter.empty):
        return lambda host, name, token: token
    if ann is bool:
        return _to_bool
    if ann is int:
        return _to_int
    if ann is float:
        return _to_float
    if ann is Player:
        return lambda host, name, token: host.find_player(token, strict=True)
    if isinstance(ann, type) and issubclass(ann, enum.Enum):
        return _enum_converter(ann)
    if get_origin(ann) is Literal:
        return _choice_converter(get_args(ann))
    raise TypeError(f"unsupported command argument type: {ann!r}")


def _to_int(host: Host, name: str, token: str) -> int:
    try:
        return int(token)
    except ValueError:
        raise ArgError("bad_int", name=name) from None


def _to_float(host: Host, name: str, token: str) -> float:
    try:
        return float(token.replace(",", "."))
    except ValueError:
        raise ArgError("bad_float", name=name) from None


def _to_bool(host: Host, name: str, token: str) -> bool:
    low = token.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    raise ArgError("bad_bool", name=name)


def _enum_converter(cls: type[enum.Enum]) -> Converter:
    def convert(host: Host, name: str, token: str) -> enum.Enum:
        for member in cls:
            if member.name.lower() == token.lower() or str(member.value) == token:
                return member
        raise ArgError("bad_choice", name=name, choices="/".join(m.name.lower() for m in cls))

    return convert


def _choice_converter(options: tuple[Any, ...]) -> Converter:
    def convert(host: Host, name: str, token: str) -> Any:
        for option in options:
            if str(option).lower() == token.lower():
                return option
        raise ArgError("bad_choice", name=name, choices="/".join(map(str, options)))

    return convert

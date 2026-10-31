"""Точки входа для C++-модуля amxpy_amxx.

C++ вызывает только эти функции. Исключения наружу не выходят: ошибки плагинов
хост перехватывает сам, а всё остальное ловит :func:`_guard` — исключение
не должно дойти до движка.
"""

from __future__ import annotations

import functools
import io
import logging
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from ._host import Host

if TYPE_CHECKING:
    from ._backend import Backend

log = logging.getLogger("amxpy")
_host: Host | None = None


def _guard(default: Any = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any) -> Any:
            if _host is None:
                return default
            try:
                return fn(_host, *args)
            except BaseException:
                try:
                    log.exception("internal error in %s", fn.__name__)
                except BaseException:
                    pass
                return default

        return wrapper

    return deco


class _Console(io.TextIOBase):
    """sys.stdout/stderr → консоль сервера, построчно."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend
        self._pending = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            self._backend.server_print(line + "\n")
        return len(text)

    def flush(self) -> None:
        if self._pending:
            self._backend.server_print(self._pending + "\n")
            self._pending = ""


def boot(game_dir: str) -> None:
    """Запустить рантайм и загрузить плагины из plugins.ini; при ошибке C++ печатает трейсбек."""
    global _host
    import _amxpy  # type: ignore[import-not-found]  # встроенный модуль C++-части

    backend = cast("Backend", _amxpy)
    sys.stdout = sys.stderr = _Console(backend)
    host = Host(backend, game_dir=game_dir)
    host.start()
    _host = host
    host.boot()


@_guard(())
def natives(host: Host) -> list[tuple[str, str, str, str]]:
    return host.native_specs()


@_guard()
def on_frame(host: Host) -> None:
    host.on_frame()


@_guard()
def on_map_start(host: Host, map_name: str) -> None:
    host.on_map_start(map_name)


@_guard()
def on_map_end(host: Host) -> None:
    host.on_map_end()


@_guard()
def on_client_connect(host: Host, index: int, name: str, ip: str) -> str | None:
    return host.on_client_connect(index, name, ip)


@_guard()
def on_client_putinserver(host: Host, index: int) -> None:
    host.on_client_putinserver(index)


@_guard()
def on_client_disconnect(host: Host, index: int) -> None:
    host.on_client_disconnect(index)


@_guard(False)
def on_client_command(host: Host, index: int, argv: list[str], args: str, handled: bool = False) -> bool:
    return host.on_client_command(index, argv, args, handled)


@_guard()
def on_server_command(host: Host, argv: list[str]) -> None:
    host.on_server_command(argv)


@_guard()
def on_event(host: Host, hook: str, post: bool, args: Any, result: Any) -> Any:
    return host.on_event(hook, post, args, result)


@_guard(0)
def call_native(host: Host, name: str, args: Any) -> Any:
    return host.call_native(name, args)


@_guard(0)
def on_pawn_forward(host: Host, index: int, amx: int, args: list[int]) -> int:
    return host.on_pawn_forward(index, amx, args)


def shutdown() -> None:
    global _host
    if _host is None:
        return
    try:
        _host.shutdown()
    except BaseException:
        log.exception("internal error in shutdown")
    finally:
        _host = None

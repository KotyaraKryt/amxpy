"""Цикл asyncio, встроенный в игровой цикл сервера."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class FrameLoop(asyncio.SelectorEventLoop):
    """Цикл asyncio, который прокачивается кадрами сервера, а не крутится сам.

    После :meth:`attach` asyncio считает цикл запущенным в этом потоке:
    работают ``get_running_loop()``, задачи и сторонние async-библиотеки.
    Каждый кадр сервер вызывает :meth:`tick` — один проход с нулевым
    таймаутом ``select``, поэтому кадр никогда не ждёт сеть.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        super().__init__()
        self._clock = clock or time.monotonic
        self._attached = False

    def time(self) -> float:
        return self._clock()

    def attach(self) -> None:
        self._run_forever_setup()  # type: ignore[attr-defined]  # приватный API asyncio
        self._attached = True

    def tick(self) -> None:
        self._stopping = True  # _run_once с нулевым таймаутом select
        try:
            self._run_once()  # type: ignore[attr-defined]
        finally:
            self._stopping = False

    def detach(self) -> None:
        if self._attached:
            self._attached = False
            self._run_forever_cleanup()  # type: ignore[attr-defined]

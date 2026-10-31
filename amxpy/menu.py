"""Меню выбора клавишами 1–9 и 0 (ShowMenu).

    shop = Menu("Магазин")

    @shop.item("AK-47 — $2500", enabled=lambda p: p.money >= 2500)
    def buy_ak(player: Player) -> None: ...

    shop.show(player)
    choice = await Menu.ask(player, "Следующая карта?", ["de_dust2", "de_inferno"], timeout=15)

Теги цвета в текстах: ``!y`` жёлтый, ``!w`` белый, ``!r`` красный, ``!d`` серый, ``!R`` — к правому краю.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from . import _state
from .player import Player

R = TypeVar("R")


class ItemDecorator(Protocol):
    """Декоратор пункта меню: функция принимает выбравшего игрока."""

    def __call__(self, fn: Callable[[Player], R], /) -> Callable[[Player], R]: ...

_TAGS = re.compile(r"!([ywrdR])")


def menu_colors(text: str) -> str:
    return _TAGS.sub(lambda m: "\\" + m.group(1), text)


@dataclass(eq=False)
class MenuItem:
    """Пункт меню: текст (или функция от игрока), обработчик, видимость, доступность, данные."""
    title: str | Callable[[Player], str]
    callback: Callable[[Player], Any] | None = None
    visible: Callable[[Player], bool] | None = None
    enabled: Callable[[Player], bool] | None = None
    data: Any = None

    def label(self, player: Player) -> str:
        """Текст пункта для этого игрока."""
        return self.title(player) if callable(self.title) else self.title


class Menu:
    """Меню со страницами: клавиши 1–7 — пункты, 8/9 — листать, 0 — выход.

    Теги цвета в текстах: ``!y`` жёлтый, ``!w`` белый, ``!r`` красный,
    ``!d`` серый, ``!R`` — выравнивание к правому краю.

    #### Параметры
    - `title` — заголовок (строка или функция от игрока).
    - `per_page` — пунктов на странице, 1–7.
    - `exit` — показывать «0. Выход».
    - `timeout` — секунд до автозакрытия (``None`` — висит до выбора).

    #### Пример
    ```python
    shop = Menu("Магазин")

    @shop.item("Броня !y($1000)", enabled=lambda p: p.money >= 1000)
    def armor(player: Player) -> None:
        player.money -= 1000
        player.armor = 100

    shop.show(player)
    ```
    """

    def __init__(
        self,
        title: str | Callable[[Player], str],
        *,
        per_page: int = 7,
        exit: bool = True,
        timeout: float | None = None,
    ) -> None:
        if not 1 <= per_page <= 7:
            raise ValueError("per_page must be 1..7")
        self.title = title
        self.per_page = per_page
        self.exit = exit
        self.timeout = timeout
        self.items: list[MenuItem] = []

    def item(
        self,
        title: str | Callable[[Player], str],
        *,
        visible: Callable[[Player], bool] | None = None,
        enabled: Callable[[Player], bool] | None = None,
        data: Any = None,
    ) -> ItemDecorator:
        """Пункт меню-декоратор; функция вызывается с выбравшим игроком.

        #### Параметры
        - `title` — текст пункта или функция от игрока.
        - `visible` — показывать ли пункт этому игроку.
        - `enabled` — активен ли пункт (неактивный — серый).
        - `data` — любые данные пункта (``item.data``).

        #### Пример
        ```python
        @shop.item(lambda p: f"Ваш ник: !y{p.name}", visible=lambda p: p.alive)
        def whoami(player: Player) -> None: ...
        ```
        """

        def deco(fn: Callable[[Player], R]) -> Callable[[Player], R]:
            self.items.append(MenuItem(title, fn, visible, enabled, data))
            return fn

        return deco

    def add(
        self,
        title: str | Callable[[Player], str],
        callback: Callable[[Player], Any] | None = None,
        *,
        visible: Callable[[Player], bool] | None = None,
        enabled: Callable[[Player], bool] | None = None,
        data: Any = None,
    ) -> MenuItem:
        """Добавить пункт без декоратора; возвращает :class:`MenuItem`.

        #### Пример
        ```python
        for n, weapon in enumerate(weapons):
            menu.add(weapon.title, lambda p, w=weapon: give(p, w), data=n)
        ```
        """
        item = MenuItem(title, callback, visible, enabled, data)
        self.items.append(item)
        return item

    def show(self, player: Player, *, page: int = 0) -> None:
        """Показать меню игроку (``page`` — с нуля); старое меню закроется."""
        _state.current().show_menu(player, self, page)

    def close(self, player: Player) -> None:
        """Закрыть меню у игрока, если показано именно оно."""
        _state.current().close_menu(player, self)

    async def choose(self, player: Player, *, timeout: float | None = None) -> MenuItem | None:
        """Показать меню и дождаться выбора.

        #### Возвращает
        Выбранный :class:`MenuItem` или ``None``: выход, тайм-аут, другое меню, игрок вышел.

        #### Пример
        ```python
        item = await menu.choose(player, timeout=10)
        if item is not None:
            player.print(f"Выбрано: {item.data}")
        ```
        """
        host = _state.current()
        future: asyncio.Future[MenuItem | None] = host.loop.create_future()
        host.show_menu(player, self, 0, future=future)
        try:
            if timeout is None:
                return await future
            async with asyncio.timeout(timeout):
                return await future
        except TimeoutError:
            host.close_menu(player, self)
            return None

    @classmethod
    async def ask(
        cls, player: Player, title: str, options: Sequence[str], *, timeout: float | None = None
    ) -> int | None:
        """Быстрый вопрос с вариантами: номер выбранного (с 0) или ``None``.

        #### Пример
        ```python
        choice = await Menu.ask(player, "Карта?", ["de_dust2", "de_inferno"], timeout=15)
        if choice is not None:
            server.change_level(maps[choice])
        ```
        """
        menu = cls(title)
        for index, option in enumerate(options):
            menu.add(option, data=index)
        item = await menu.choose(player, timeout=timeout)
        return None if item is None else item.data

    def render(self, player: Player, page: int, labels: dict[str, str]) -> tuple[str, int, dict[int, Any], int]:
        """Текст меню, маска клавиш, слоты и номер страницы — для рантайма."""
        items = [it for it in self.items if it.visible is None or it.visible(player)]
        pages = max(1, -(-len(items) // self.per_page))
        page = max(0, min(page, pages - 1))
        title = self.title(player) if callable(self.title) else self.title
        lines = [menu_colors("!y" + title) + (f"\\R{page + 1}/{pages}" if pages > 1 else ""), ""]
        keys = 0
        slots: dict[int, Any] = {}
        for key, item in enumerate(items[page * self.per_page : (page + 1) * self.per_page], 1):
            label = menu_colors(item.label(player))
            if item.enabled is None or item.enabled(player):
                lines.append(f"\\r{key}.\\w {label}")
                keys |= 1 << (key - 1)
                slots[key] = item
            else:
                lines.append(f"\\d{key}. {label}")
        if pages > 1:
            lines.append("")
            for key, slot, active in ((8, "back", page > 0), (9, "next", page < pages - 1)):
                if active:
                    lines.append(f"\\r{key}.\\w {labels[slot]}")
                    keys |= 1 << (key - 1)
                    slots[key] = slot
                else:
                    lines.append(f"\\d{key}. {labels[slot]}")
        if self.exit:
            if pages == 1:
                lines.append("")
            lines.append(f"\\r0.\\w {labels['exit']}")
            keys |= 1 << 9
            slots[0] = "exit"
        return "\n".join(lines), keys, slots, page

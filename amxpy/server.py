"""Фасад сервера: ``from amxpy import server``."""

from __future__ import annotations

from . import _backend as B
from . import _state
from .player import Player, colorize


class Server:
    """Сервер целиком: ``from amxpy import server``.

    #### Пример
    ```python
    server.print(f"!gКарта: !t{server.map}")
    for player in server.players:
        player.money += 1000
    ```
    """
    @property
    def players(self) -> list[Player]:
        """Игроки на сервере (без вышедших)."""
        return [p for p in _state.current().players.values() if p.connected]

    @property
    def map(self) -> str:
        """Текущая карта: ``de_dust2``."""
        return _state.current().backend.map_name()

    @property
    def max_players(self) -> int:
        """Число слотов сервера."""
        return _state.current().backend.max_players()

    @property
    def time(self) -> float:
        """Игровое время (gpGlobals->time)."""
        return _state.current().backend.game_time()

    def print(self, text: str) -> None:
        """Сообщение в чат всем игрокам.

        Теги цвета: ``!g`` — зелёный, ``!t`` — цвет команды, ``!y`` — обычный.
        """
        _state.current().backend.client_print(0, B.PRINT_CHAT, colorize(text))

    def console(self, text: str) -> None:
        """Строка в консоль сервера."""
        _state.current().backend.server_print(text + "\n")

    def command(self, command: str) -> None:
        """Команда серверной консоли (выполнится в начале следующего кадра).

        #### Пример
        ```python
        server.command("mp_restartgame 1")
        ```
        """
        _state.current().backend.server_command(command)

    def change_level(self, map_name: str) -> None:
        """Сменить карту: ``server.change_level("de_inferno")``."""
        self.command(f"changelevel {map_name}")

    def find_player(self, query: str) -> Player | None:
        """Игрок по ``#userid``, SteamID или части ника.

        #### Возвращает
        Игрок или ``None``, если никого или подходят несколько.
        """
        return _state.current().find_player(query)

    def cvar(self, name: str) -> str | None:
        """Значение любого cvar'а сервера строкой; ``None`` — такого нет."""
        return _state.current().backend.cvar_get(name)

    def set_cvar(self, name: str, value: object) -> None:
        """Изменить cvar сервера: ``server.set_cvar("mp_freezetime", 3)``."""
        _state.current().backend.cvar_set(name, str(value))


server = Server()

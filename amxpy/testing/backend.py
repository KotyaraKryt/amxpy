"""Бэкенд фейкового сервера: состояние игроков, cvar'ов и вывода в памяти."""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import _backend as B
from .._bridge import read_natives
from ..player import strip_colors

if TYPE_CHECKING:
    from . import FakeServer


def _default_props() -> dict[str, float]:
    return {"health": 100.0, "armor": 0.0, "frags": 0.0, "deaths": 0.0, "money": 800.0}


@dataclass
class FakeClient:
    index: int
    userid: int
    name: str
    ip: str
    steam_id: str
    auth: str = "STEAM_ID_PENDING"
    bot: bool = False
    team: int = 2
    flags: int = 0
    alive: bool = True
    props: dict[str, float] = field(default_factory=_default_props)
    info: dict[str, str] = field(default_factory=dict)
    chat: list[str] = field(default_factory=list)
    console: list[str] = field(default_factory=list)
    center: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    hud: list[str] = field(default_factory=list)
    dhud: list[str] = field(default_factory=list)
    menu_text: str | None = None  # меню на экране (сырой текст с \y \w ...)
    menu_keys: int = 0
    menu_buffer: str = ""
    items: list[str] = field(default_factory=lambda: ["knife"])  # оружие без префикса weapon_


@dataclass
class FakeOut:
    """Выходной аргумент подставного натива: строка, число или список в ``.value``."""

    value: Any


# id user-сообщений фейкового сервера
USER_MESSAGES = {"SayText": 76, "ShowMenu": 96, "ScreenFade": 98, "Money": 102}


class FakeBackend:
    """Реализация :class:`amxpy._backend.Backend` поверх словарей."""

    def __init__(self, server: FakeServer, game_dir: Path, *, max_players: int, map_name: str) -> None:
        self.server = server
        self._game_dir = game_dir
        self._max_players = max_players
        self.map = map_name
        self.time = 0.0
        self.clients: dict[int, FakeClient] = {}
        self.cvars: dict[str, str] = {}
        self.pinned: set[str] = set()  # cvar'ы, заданные тестом: exec их не перезаписывает
        self.lines: list[str] = []  # консоль и журнал сервера
        self.commands: list[str] = []  # выполненные серверные команды
        self.engine_commands: set[str] = set()
        self.hooks: set[str] = set()
        self.natives: dict[str, tuple[str, str]] = {}
        self.forwards: list[tuple[str, tuple[Any, ...]]] = []
        self.amxx_natives: dict[str, Callable[..., Any]] = {}  # подставные нативы AMXX для amxpy.amxx
        self.bridges: list[list[str]] = []  # имена нативов каждого загруженного моста
        self.amx_cells: dict[int, int] = {}  # память AMX плагина-приёмника Pawn-форвардов
        self.entities: dict[int, str] = {}
        self.messages: list[tuple[int, int, int, list[tuple[str, Any]]]] = []  # (dest, тип, игрок, данные)

    # --- сервер ---
    def server_print(self, text: str) -> None:
        self.lines.extend(text.rstrip("\n").split("\n"))

    def log(self, level: int, text: str) -> None:
        self.lines.extend(text.split("\n"))

    def server_command(self, command: str) -> None:
        command = command.strip()
        self.commands.append(command)
        self.server._server_command(command)

    def server_execute(self) -> None:
        self.server._flush()

    def map_name(self) -> str:
        return self.map

    def max_players(self) -> int:
        return self._max_players

    def game_time(self) -> float:
        return self.time

    def game_dir(self) -> str:
        return str(self._game_dir)

    # --- игроки ---
    def userid(self, index: int) -> int:
        client = self.clients.get(index)
        return client.userid if client is not None else 0

    def player_name(self, index: int) -> str:
        return self.clients[index].name

    def player_auth(self, index: int) -> str:
        client = self.clients.get(index)
        return client.auth if client is not None else ""

    def player_ip(self, index: int) -> str:
        return self.clients[index].ip

    def player_info(self, index: int, key: str) -> str:
        return self.clients[index].info.get(key, "")

    def is_bot(self, index: int) -> bool:
        return self.clients[index].bot

    def is_alive(self, index: int) -> bool:
        return self.clients[index].alive

    def player_team(self, index: int) -> int:
        return self.clients[index].team

    def player_flags(self, index: int) -> int:
        return self.clients[index].flags

    def get_prop(self, index: int, name: str) -> float:
        return self.clients[index].props[name]

    def set_prop(self, index: int, name: str, value: float) -> None:
        if name not in B.PLAYER_PROPS:
            raise KeyError(name)
        self.clients[index].props[name] = float(value)

    def client_print(self, index: int, kind: int, text: str) -> None:
        targets = [self.clients[index]] if index else list(self.clients.values())
        for client in targets:
            if kind == B.PRINT_CHAT:
                client.chat.append(strip_colors(text))
            elif kind == B.PRINT_CENTER:
                client.center.append(text)
            else:
                client.console.append(text.rstrip("\n"))

    def client_command(self, index: int, command: str) -> None:
        self.clients[index].commands.append(command.strip())

    # --- сущности ---
    def entity_classname(self, index: int) -> str:
        if index in self.clients:
            return "player"
        return self.entities.get(index, "")

    # --- cvar'ы и команды ---
    def cvar_register(self, name: str, value: str, flags: int) -> None:
        self.cvars.setdefault(name, value)

    def cvar_get(self, name: str) -> str | None:
        return self.cvars.get(name)

    def cvar_set(self, name: str, value: str) -> None:
        self.cvars[name] = str(value)

    def register_server_command(self, name: str) -> None:
        self.engine_commands.add(name)

    # --- сообщения клиентам ---
    def user_message(self, name: str) -> int:
        return USER_MESSAGES.get(name, 0)

    def send_message(self, dest: int, msg_type: int, index: int, data: list[tuple[str, Any]]) -> None:
        self.messages.append((dest, msg_type, index, list(data)))
        values = [value for _, value in data]
        for client in [self.clients[index]] if index else list(self.clients.values()):
            if msg_type == USER_MESSAGES["ShowMenu"]:
                keys, _seconds, more, chunk = values
                client.menu_buffer += chunk
                if not more:
                    text, client.menu_buffer = client.menu_buffer, ""
                    client.menu_text = text if keys or text else None  # пустое меню закрывает текущее
                    client.menu_keys = keys
            elif msg_type == B.SVC_TEMPENTITY and values[:1] == [29]:  # TE_TEXTMESSAGE
                client.hud.append(values[-1])
            elif msg_type == B.SVC_DIRECTOR and values[1:2] == [6]:  # DRC_CMD_MESSAGE
                client.dhud.append(values[-1])

    # --- хуки, нативы, форварды ---
    def enable_hook(self, hook: str, enabled: bool) -> bool:
        (self.hooks.add if enabled else self.hooks.discard)(hook)
        return True

    def register_native(self, name: str, params: str, returns: str) -> bool:
        self.natives[name] = (params, returns)
        return True

    def forward_execute(self, name: str, types: str, args: tuple[Any, ...]) -> int:
        self.forwards.append((name, tuple(args)))
        return 0

    # --- чужие нативы: подставные функции вместо модулей AMXX ---
    def load_bridge(self, path: str) -> tuple[int, list[int], str]:
        names = read_natives(Path(path).read_bytes())  # заодно проверка формата образа
        self.bridges.append(names)
        known = [n for n in names if n in self.amxx_natives]
        addresses = [self._native_address(n) if n in self.amxx_natives else 0 for n in names]
        missing = next((n for n in names if n not in known), None)
        error = f'Plugin uses an unknown function (name "{missing}") - check your modules.ini.' if missing else ""
        return len(self.bridges) - 1, addresses, error

    # --- память AMX: ячейки по адресам, как в куче плагина-приёмника ---
    def amx_read(self, amx: int, address: int, count: int) -> list[int]:
        if any(address + 4 * i not in self.amx_cells for i in range(count)):
            raise IndexError("AMX address out of range")
        return [self.amx_cells[address + 4 * i] for i in range(count)]

    def amx_string(self, amx: int, address: int, limit: int) -> str:
        data = bytearray()
        for i in range(limit):
            cell = self.amx_read(amx, address + 4 * i, 1)[0]
            if cell == 0:
                break
            data.append(cell & 0xFF)
        return data.decode("utf-8", errors="replace")

    def amx_write(self, amx: int, address: int, cells: list[int]) -> None:
        self.amx_read(amx, address, len(cells))  # проверка границ
        for i, cell in enumerate(cells):
            self.amx_cells[address + 4 * i] = int(cell)

    def _native_address(self, name: str) -> int:
        """Постоянный «адрес» подставного натива: номер в порядке появления."""
        return 1 + list(self.amxx_natives).index(name)

    def call_bridge(self, bridge: int, index: int, address: int, args: list[tuple[str, object]]) -> tuple[int, list, int]:
        name = self.bridges[bridge][index]
        assert address == self._native_address(name)
        values: list[Any] = []
        outputs: list[FakeOut] = []
        for code, value in args:
            if code in "brqav":
                out = FakeOut("" if code == "b" else list(value) if code in "av" else value)  # type: ignore[call-overload]
                outputs.append(out)
                values.append(out)
            else:
                values.append(value)
        try:
            result = self.amxx_natives[name](*values)
        except Exception as exc:  # как LogError в нативе: ошибка AMX и строка в логе
            self.lines.append(f"[AMXX] {name}: {exc}")
            return 0, [o.value for o in outputs], 10
        if isinstance(result, float):
            result = struct.unpack("<i", struct.pack("<f", result))[0]
        return int(result or 0), [o.value for o in outputs], 0

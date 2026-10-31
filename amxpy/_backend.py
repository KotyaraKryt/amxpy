"""Граница между Python-рантаймом amxpy и игровым сервером.

На сервере бэкенд — встроенный модуль ``_amxpy`` из C++-модуля AMXX,
в тестах — :class:`amxpy.testing.backend.FakeBackend`. Оба реализуют
протокол :class:`Backend`: рантайм обращается к серверу только через него.

Коды типов нативов и форвардов (по символу на параметр):
``i`` — int, ``f`` — float, ``b`` — bool, ``s`` — str, ``p`` — игрок (индекс),
``v`` — нет значения (только для результата).
"""

from __future__ import annotations

from typing import Protocol

# Куда печатать сообщение игроку
PRINT_CHAT = 0
PRINT_CONSOLE = 1
PRINT_CENTER = 2

# Уровни журнала
LOG_INFO = 0
LOG_WARNING = 1
LOG_ERROR = 2

# Числовые свойства игрока для get_prop/set_prop
PLAYER_PROPS = ("health", "armor", "frags", "deaths", "money")

# Получатели сообщений (MSG_*)
MSG_BROADCAST = 0  # всем, ненадёжно
MSG_ONE = 1  # одному, надёжно
MSG_ALL = 2  # всем, надёжно
MSG_ONE_UNRELIABLE = 8

# Служебные сообщения движка (svc_*)
SVC_TEMPENTITY = 23
SVC_DIRECTOR = 51

# Коды данных send_message: b byte, c char, s short, l long, a angle, o coord, S string, e entity


class Backend(Protocol):
    # --- сервер ---
    def server_print(self, text: str, /) -> None: ...
    def log(self, level: int, text: str, /) -> None: ...
    def server_command(self, command: str, /) -> None: ...  # в буфер команд
    def server_execute(self) -> None: ...  # выполнить буфер команд сейчас
    def map_name(self) -> str: ...
    def max_players(self) -> int: ...
    def game_time(self) -> float: ...
    def game_dir(self) -> str: ...

    # --- игроки (index 1..max_players) ---
    def userid(self, index: int, /) -> int: ...  # 0 — слот свободен
    def player_name(self, index: int, /) -> str: ...
    def player_auth(self, index: int, /) -> str: ...  # SteamID; "" или *_PENDING, пока неизвестен
    def player_ip(self, index: int, /) -> str: ...
    def player_info(self, index: int, key: str, /) -> str: ...  # setinfo
    def is_bot(self, index: int, /) -> bool: ...
    def is_alive(self, index: int, /) -> bool: ...
    def player_team(self, index: int, /) -> int: ...
    def player_flags(self, index: int, /) -> int: ...  # флаги админа AMXX
    def get_prop(self, index: int, name: str, /) -> float: ...
    def set_prop(self, index: int, name: str, value: float, /) -> None: ...
    def client_print(self, index: int, kind: int, text: str, /) -> None: ...  # index 0 — всем
    def client_command(self, index: int, command: str, /) -> None: ...

    # --- сущности ---
    def entity_classname(self, index: int, /) -> str: ...  # "" — сущности нет

    # --- cvar'ы и серверные команды ---
    def cvar_register(self, name: str, value: str, flags: int, /) -> None: ...
    def cvar_get(self, name: str, /) -> str | None: ...
    def cvar_set(self, name: str, value: str, /) -> None: ...
    def register_server_command(self, name: str, /) -> None: ...

    # --- сообщения клиентам ---
    def user_message(self, name: str, /) -> int: ...  # id user-сообщения ("ShowMenu"); 0 — нет
    def send_message(self, dest: int, msg_type: int, index: int, data: list[tuple[str, object]], /) -> None: ...

    # --- хуки, нативы, форварды ---
    def enable_hook(self, hook: str, enabled: bool, /) -> bool: ...  # False — хук недоступен
    def register_native(self, name: str, params: str, returns: str, /) -> bool: ...  # False — со следующей карты
    def forward_execute(self, name: str, types: str, args: tuple, /) -> int: ...

    # --- чужие нативы (amxpy.amxx) ---
    # (id моста или -1, адреса нативов по порядку таблицы (0 — не найден), ошибка загрузки)
    def load_bridge(self, path: str, /) -> tuple[int, list[int], str]: ...
    # (результат, значения выходных аргументов по порядку, код ошибки AMX)
    def call_bridge(self, bridge: int, index: int, address: int, args: list[tuple[str, object]], /) -> tuple[int, list, int]: ...

    # --- память AMX во время Pawn-форварда (amx — указатель из on_pawn_forward) ---
    def amx_read(self, amx: int, address: int, count: int, /) -> list[int]: ...
    def amx_string(self, amx: int, address: int, limit: int, /) -> str: ...
    def amx_write(self, amx: int, address: int, cells: list[int], /) -> None: ...

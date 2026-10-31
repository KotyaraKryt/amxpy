"""Сообщения клиенту.

    Message("ScreenFade", to=player).short(4096).short(4096).short(0).byte(0).byte(0).byte(0).byte(100).send()

    with Message("ScreenShake", to=player) as m:
        m.short(1 << 14).short(1 << 12).short(1 << 14)

Сообщение собирается целиком и уходит одним вызовом — незакрытого message_begin не бывает.
"""

from __future__ import annotations

from typing import Any

from . import _backend as B
from . import _state
from .player import Player


def utf8_truncate(text: str, limit: int) -> str:
    """Обрезать до ``limit`` байт UTF-8, не разрезая символ."""
    data = text.encode("utf-8")
    return text if len(data) <= limit else data[:limit].decode("utf-8", errors="ignore")


def utf8_chunks(text: str, limit: int) -> list[str]:
    """Нарезать на куски не длиннее ``limit`` байт UTF-8 по границам символов."""
    chunks = []
    while text:
        chunk = utf8_truncate(text, limit)
        chunks.append(chunk)
        text = text[len(chunk) :]
    return chunks


class Message:
    """User-сообщение клиенту по имени (``"ScreenFade"``) или служебное по номеру.

    Сообщение собирается целиком и уходит одним вызовом :meth:`send`
    (или при выходе из ``with``) — незакрытого message_begin не бывает.

    #### Параметры
    - `kind` — имя user-сообщения или номер SVC_*.
    - `to` — игрок; ``None`` — всем.
    - `reliable` — гарантированная доставка (MSG_ONE/MSG_ALL).

    #### Пример
    ```python
    with Message("ScreenFade", to=player) as m:
        m.short(4096).short(4096).short(0)
        m.byte(255).byte(0).byte(0).byte(100)
    ```
    """

    def __init__(self, kind: str | int, *, to: Player | None = None, reliable: bool = True) -> None:
        self.kind = kind
        self.to = to
        self.reliable = reliable
        self.data: list[tuple[str, Any]] = []

    def byte(self, value: int) -> Message:
        """WRITE_BYTE: 0–255."""
        self.data.append(("b", int(value)))
        return self

    def char(self, value: int) -> Message:
        """WRITE_CHAR: −128–127."""
        self.data.append(("c", int(value)))
        return self

    def short(self, value: int) -> Message:
        """WRITE_SHORT: −32768–32767."""
        self.data.append(("s", int(value)))
        return self

    def long(self, value: int) -> Message:
        """WRITE_LONG: 32-битное целое."""
        self.data.append(("l", int(value)))
        return self

    def angle(self, value: float) -> Message:
        """WRITE_ANGLE: угол в градусах."""
        self.data.append(("a", float(value)))
        return self

    def coord(self, value: float) -> Message:
        """WRITE_COORD: координата."""
        self.data.append(("o", float(value)))
        return self

    def string(self, value: str) -> Message:
        """WRITE_STRING: строка UTF-8."""
        self.data.append(("S", str(value)))
        return self

    def entity(self, value: int) -> Message:
        """WRITE_ENTITY: индекс сущности."""
        self.data.append(("e", int(value)))
        return self

    def send(self) -> None:
        """Отправить сообщение.

        #### Исключения
        - `LookupError` — такого user-сообщения у мода нет.
        - `StaleHandleError` — адресат вышел.
        """
        backend = _state.current().backend
        msg_type = self.kind if isinstance(self.kind, int) else backend.user_message(self.kind)
        if not msg_type:
            raise LookupError(f"unknown user message {self.kind!r}")
        if self.to is None:
            dest, index = (B.MSG_ALL if self.reliable else B.MSG_BROADCAST), 0
        else:
            self.to._backend()  # вышедший игрок — StaleHandleError
            dest, index = (B.MSG_ONE if self.reliable else B.MSG_ONE_UNRELIABLE), self.to.index
        backend.send_message(dest, msg_type, index, self.data)

    def __enter__(self) -> Message:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if exc_type is None:
            self.send()

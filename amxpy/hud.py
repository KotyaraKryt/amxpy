"""HUD и DHUD.

    hud = Hud(y=0.25, color=(0, 255, 0), hold=3)
    hud.show(player, "Раунд начался")

    banner = DirectorHud(color=(255, 120, 0))
    banner.show_all("Бомба заложена!")
"""

from __future__ import annotations

import itertools
import struct
from collections.abc import Sequence

from . import _backend as B
from . import _state
from .message import utf8_truncate
from .player import Player

TE_TEXTMESSAGE = 29
DRC_CMD_MESSAGE = 6

_channels = itertools.cycle(range(1, 5))


def _fixed(value: float, scale: int, *, signed: bool) -> int:
    raw = int(value * scale)
    return max(-32768, min(32767, raw)) if signed else max(0, min(65535, raw))


def _rgba(color: Sequence[int]) -> tuple[int, int, int, int]:
    r, g, b, *alpha = color
    return int(r) & 255, int(g) & 255, int(b) & 255, (int(alpha[0]) if alpha else 255) & 255


def _float_bits(value: float) -> int:
    return struct.unpack("<i", struct.pack("<f", value))[0]


class _HudText:
    def show(self, player: Player, text: str) -> None:
        """Показать текст игроку (``\\n`` — перенос строки)."""
        player._backend()  # вышедший игрок — StaleHandleError
        self._send(player.index, text)

    def show_all(self, text: str) -> None:
        """Показать текст всем игрокам на сервере."""
        for player in list(_state.current().players.values()):
            if player.connected:
                self._send(player.index, text)

    def _send(self, index: int, text: str) -> None:
        raise NotImplementedError


class Hud(_HudText):
    """Обычный HUD-текст (TE_TEXTMESSAGE): до 479 байт, 4 канала.

    Сообщения одного канала заменяют друг друга; без ``channel`` каждый
    ``Hud`` берёт следующий из 1–4.

    #### Параметры
    - `x` — позиция по горизонтали 0–1; ``-1`` — по центру.
    - `y` — позиция по вертикали 0–1; ``-1`` — по центру.
    - `color` — цвет ``(r, g, b)`` или ``(r, g, b, a)``.
    - `effect` — 0 — появление, 1 — мерцание, 2 — печать по буквам.
    - `fade_in` — секунд появления.
    - `fade_out` — секунд исчезновения.
    - `hold` — секунд на экране.
    - `fx_time` — время эффекта 2 на букву.
    - `color2` — цвет подсветки для эффекта 2.
    - `channel` — канал 1–4 (``None`` — следующий свободный по кругу).

    #### Пример
    ```python
    info = Hud(y=0.25, color=(0, 200, 255), hold=4)
    info.show(player, f"Здоровье: {player.health}")
    ```
    """

    MAX_BYTES = 479

    def __init__(
        self,
        *,
        x: float = -1.0,
        y: float = 0.35,
        color: Sequence[int] = (255, 255, 255),
        effect: int = 0,
        fade_in: float = 0.1,
        fade_out: float = 0.2,
        hold: float = 3.0,
        fx_time: float = 0.0,
        color2: Sequence[int] = (255, 255, 255),
        channel: int | None = None,
    ) -> None:
        if channel is not None and not 1 <= channel <= 4:
            raise ValueError("HUD channel must be 1..4")
        self.x, self.y = x, y
        self.color, self.color2 = color, color2
        self.effect = effect
        self.fade_in, self.fade_out, self.hold, self.fx_time = fade_in, fade_out, hold, fx_time
        self.channel = channel if channel is not None else next(_channels)

    def clear(self, player: Player | None = None) -> None:
        """Стереть сообщение этого канала у игрока (или у всех)."""
        hold, self.hold = self.hold, 0.0
        try:
            self.show(player, "") if player is not None else self.show_all("")
        finally:
            self.hold = hold

    def _send(self, index: int, text: str) -> None:
        r, g, b, a = _rgba(self.color)
        r2, g2, b2, a2 = _rgba(self.color2)
        data: list[tuple[str, object]] = [
            ("b", TE_TEXTMESSAGE),
            ("b", self.channel),
            ("s", _fixed(self.x, 1 << 13, signed=True)),
            ("s", _fixed(self.y, 1 << 13, signed=True)),
            ("b", self.effect),
            ("b", r), ("b", g), ("b", b), ("b", a),
            ("b", r2), ("b", g2), ("b", b2), ("b", a2),
            ("s", _fixed(self.fade_in, 1 << 8, signed=False)),
            ("s", _fixed(self.fade_out, 1 << 8, signed=False)),
            ("s", _fixed(self.hold, 1 << 8, signed=False)),
        ]  # fmt: skip
        if self.effect == 2:
            data.append(("s", _fixed(self.fx_time, 1 << 8, signed=False)))
        data.append(("S", utf8_truncate(text, self.MAX_BYTES)))
        _state.current().backend.send_message(B.MSG_ONE_UNRELIABLE, B.SVC_TEMPENTITY, index, data)


class DirectorHud(_HudText):
    """Крупный HUD (director message, «DHUD»): до 127 байт, на экране до 8 сообщений.

    #### Параметры
    - `x` — позиция по горизонтали 0–1; ``-1`` — по центру.
    - `y` — позиция по вертикали 0–1; ``-1`` — по центру.
    - `color` — цвет ``(r, g, b)``.
    - `effect` — 0 — появление, 1 — мерцание, 2 — печать по буквам.
    - `fade_in` — секунд появления.
    - `fade_out` — секунд исчезновения.
    - `hold` — секунд на экране.
    - `fx_time` — время эффекта 2 на букву.

    #### Пример
    ```python
    banner = DirectorHud(y=0.3, color=(255, 140, 0), hold=5)
    banner.show_all("Бомба заложена!")
    ```
    """

    MAX_BYTES = 127

    def __init__(
        self,
        *,
        x: float = -1.0,
        y: float = 0.35,
        color: Sequence[int] = (255, 255, 255),
        effect: int = 0,
        fade_in: float = 0.1,
        fade_out: float = 0.2,
        hold: float = 3.0,
        fx_time: float = 0.0,
    ) -> None:
        self.x, self.y = x, y
        self.color = color
        self.effect = effect
        self.fade_in, self.fade_out, self.hold, self.fx_time = fade_in, fade_out, hold, fx_time

    def _send(self, index: int, text: str) -> None:
        payload = utf8_truncate(text, self.MAX_BYTES)
        r, g, b, _ = _rgba(self.color)
        data: list[tuple[str, object]] = [
            ("b", len(payload.encode("utf-8")) + 31),  # длина остатка сообщения
            ("b", DRC_CMD_MESSAGE),
            ("b", self.effect),
            ("l", (r << 16) | (g << 8) | b),
            ("l", _float_bits(self.x)),
            ("l", _float_bits(self.y)),
            ("l", _float_bits(self.fade_in)),
            ("l", _float_bits(self.fade_out)),
            ("l", _float_bits(self.hold)),
            ("l", _float_bits(self.fx_time)),
            ("S", payload),
        ]
        _state.current().backend.send_message(B.MSG_ONE_UNRELIABLE, B.SVC_DIRECTOR, index, data)

"""Контекст выполнения: какой плагин сейчас работает.

Хост вызывает код плагина, выставив :data:`current`. Всё, что плагин создаёт
в этот момент (задачи asyncio, PlayerState, конфиги), записывается на него.
Задачи наследуют контекст сами, поэтому владение не теряется и в async-коде,
а выгрузка плагина освобождает всё, что он создал.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._host import PluginInstance

current: ContextVar[PluginInstance | None] = ContextVar("amxpy_plugin", default=None)


def instance() -> PluginInstance | None:
    """Экземпляр плагина, в контексте которого выполняется код (или None)."""
    return current.get()

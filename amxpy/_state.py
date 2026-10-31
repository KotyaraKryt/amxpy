"""Активный хост рантайма (один на процесс)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._host import Host

host: Host | None = None


def current() -> Host:
    """Работающий хост; вне сервера и тестового FakeServer — ошибка."""
    if host is None:
        raise RuntimeError("amxpy runtime is not running")
    return host

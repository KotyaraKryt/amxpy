"""Хранилище плагина на SQLite: таблица dataclass'ов по ключу.

    table = Table("vip", Vip, key="steam_id")   # addons/amxpy/data/<плагин>.db
    await table.create()
    vip = await table.get(player.steam_id)

Запросы выполняются вне игрового потока, кадр их не ждёт. Записи хранятся
как JSON; поля datetime/date сохраняются в ISO-формате.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import sqlite3
import threading
import types
import typing
from pathlib import Path
from typing import Any, Generic, TypeVar, get_args, get_origin

from . import _state, context

T = TypeVar("T")


def _decoder(hint: Any) -> Any:
    if get_origin(hint) in (typing.Union, types.UnionType):
        hint = next((a for a in get_args(hint) if a is not type(None)), hint)
    if hint is dt.datetime:
        return dt.datetime.fromisoformat
    if hint is dt.date:
        return dt.date.fromisoformat
    return None


class Table(Generic[T]):
    """Таблица SQLite с dataclass'ами по ключу: ``addons/amxpy/data/<плагин>.db``.

    Запросы идут вне игрового потока — кадр их не ждёт. Записи хранятся
    как JSON; ``datetime`` и ``date`` — в ISO-формате.

    #### Параметры
    - `name` — имя таблицы.
    - `cls` — dataclass записей.
    - `key` — поле-ключ.
    - `file` — свой файл базы вместо ``data/<плагин>.db``.

    #### Пример
    ```python
    @dataclass
    class Vip:
        steam_id: str
        until: datetime

    table = Table("vip", Vip, key="steam_id")

    @plugin.on(events.Init)
    async def setup(e: events.Init) -> None:
        await table.create()
    ```
    """
    def __init__(self, name: str, cls: type[T], *, key: str, file: str | Path | None = None) -> None:
        if not dataclasses.is_dataclass(cls):
            raise TypeError("Table stores dataclasses")
        self.name = name
        self.cls = cls
        self.key = key
        self._file = Path(file) if file is not None else None
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()
        hints = typing.get_type_hints(cls)
        self._decoders = {f.name: d for f in dataclasses.fields(cls) if (d := _decoder(hints.get(f.name)))}

    def _path(self) -> Path:
        if self._file is not None:
            return self._file
        inst = context.instance()
        return _state.current().base_dir / "data" / f"{inst.name if inst else 'amxpy'}.db"

    def _db(self, path: Path) -> sqlite3.Connection:
        if self._conn is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        return self._conn

    def _encode(self, obj: T) -> tuple[str, str]:
        data = dataclasses.asdict(obj)  # type: ignore[call-overload]
        return str(data[self.key]), json.dumps(data, default=_iso, ensure_ascii=False)

    def _decode(self, raw: str) -> T:
        data = json.loads(raw)
        for name, decode in self._decoders.items():
            if data.get(name) is not None:
                data[name] = decode(data[name])
        return self.cls(**data)

    async def _run(self, fn: Any, *args: Any) -> Any:
        path = self._path()  # контекст плагина доступен только здесь, не в потоке

        def job() -> Any:
            with self._lock:
                return fn(self._db(path), *args)

        return await _state.current().offload(job)

    async def create(self) -> None:
        """Создать таблицу, если её нет (обычно в ``events.Init``)."""
        await self._run(lambda db: db.execute(f'CREATE TABLE IF NOT EXISTS "{self.name}" (k TEXT PRIMARY KEY, v TEXT)'))

    async def get(self, key: Any) -> T | None:
        """Запись по ключу или ``None``: ``vip = await table.get(player.steam_id)``."""
        row = await self._run(lambda db: db.execute(f'SELECT v FROM "{self.name}" WHERE k = ?', (str(key),)).fetchone())
        return self._decode(row[0]) if row else None

    async def put(self, obj: T) -> None:
        """Сохранить запись (вставить или заменить по ключу)."""
        key, value = self._encode(obj)
        await self._run(lambda db: db.execute(f'INSERT OR REPLACE INTO "{self.name}" VALUES (?, ?)', (key, value)))

    async def delete(self, key: Any) -> bool:
        """Удалить запись; ``True`` — она была."""
        cur = await self._run(lambda db: db.execute(f'DELETE FROM "{self.name}" WHERE k = ?', (str(key),)))
        return bool(cur.rowcount)

    async def all(self) -> list[T]:
        """Все записи таблицы."""
        rows = await self._run(lambda db: db.execute(f'SELECT v FROM "{self.name}"').fetchall())
        return [self._decode(r[0]) for r in rows]

    def close(self) -> None:
        """Закрыть соединение с базой."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


def _iso(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")

# Хранилище и переводы

## Файлы настроек

Тексты рекламы, списки карт, правила — всё, что владелец сервера правит руками, — место
не в коде плагина, а в файле на сервере. `plugin.config_file` даёт плагину такой файл:

```python
import configparser

from amxpy import Plugin, events

plugin = Plugin("Adverts")
path = plugin.config_file("adverts.ini", default="""
    [messages]
    1 = !gНаш сайт: !texample.com
    2 = !yГруппа ВК: !gvk.com/example
""")
messages: list[str] = []


@plugin.on(events.MapStart)
def load(e: events.MapStart) -> None:
    ini = configparser.ConfigParser()
    ini.read(path, encoding="utf-8")
    messages[:] = ini["messages"].values()
```

- Файл лежит в `addons/amxpy/configs/<плагин>/adverts.ini`; можно и с подпапкой: `texts/ru.txt`.
- Если файла нет, он создаётся из `default` — общий отступ и первая пустая строка убираются.
- Существующий файл **никогда не перезаписывается**: ни при перезагрузке плагина, ни при
  `amxpy deploy`. Это файл владельца сервера.
- Формат выбираете сами: `.ini` через `configparser`, `.toml` через `tomllib`, `.json` или
  `.txt` — всё из стандартной библиотеки.
- Читайте файл в `Init` или `MapStart`: тогда правки подхватятся со сменой карты или
  командой `amxpy reload <плагин>`.

Для настроек-чисел и переключателей удобнее [cvar'ы](config.md) — их можно менять из консоли
на лету.

## Таблица SQLite { #table }

`Table` хранит dataclass'ы по ключу в `addons/amxpy/data/<плагин>.db`. Запросы идут вне
игрового потока — кадр их не ждёт.

```python
from dataclasses import dataclass
from datetime import datetime

from amxpy.storage import Table


@dataclass
class Visit:
    steam_id: str
    visits: int
    last_seen: datetime


table = Table("visits", Visit, key="steam_id")


@plugin.on(events.Init)
async def setup(e: events.Init) -> None:
    await table.create()                          # создать таблицу, если её нет


@plugin.on(events.Authorized)                     # SteamID уже известен
async def welcome(e: events.Authorized) -> None:
    player, steam_id = e.player, e.steam_id
    visit = await table.get(steam_id) or Visit(steam_id, 0, datetime.now())
    visit.visits += 1
    visit.last_seen = datetime.now()
    await table.put(visit)
```

| Метод | |
|---|---|
| `await table.create()` | создать таблицу |
| `await table.get(key)` | запись или `None` |
| `await table.put(obj)` | вставить или заменить по ключу |
| `await table.delete(key)` | удалить; `True`, если запись была |
| `await table.all()` | все записи |

Записи хранятся как JSON; `datetime` и `date` — в ISO-формате и читаются обратно теми же
типами. Свой файл базы — `Table(..., file="stats.db")`. Целиком — пример
[«С возвращением»](../examples/welcome-back.md).

!!! tip "Загружайте данные в `Authorized`"
    В `PutInServer` SteamID может быть ещё неизвестен (`STEAM_ID_PENDING`). Событие
    `Authorized` приходит, когда он есть.

## Переводы

Плагин-пакет может хранить тексты в `lang/<язык>.toml`:

=== "lang/ru.toml"

    ```toml
    welcome = "Привет, {name}!"
    vip_days = "!gVIP: осталось {days} дн."
    ```

=== "lang/en.toml"

    ```toml
    welcome = "Hello, {name}!"
    vip_days = "!gVIP: {days} days left"
    ```

```python
player.print(player.tr("welcome", name=player.name))
```

`player.tr` ищет ключ на языке игрока (setinfo `lang`, иначе язык сервера), потом в `en`,
потом в любом файле, а если не нашёл — возвращает сам ключ. Файлы `lang/` попадают в пакет
плагина при сборке.

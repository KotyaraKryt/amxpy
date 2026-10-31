# Плагин и модули

Каждый плагин начинается с одного объекта `Plugin`. Декораторы `@plugin.on`, `@plugin.command`
и остальные только **записывают** объявления, а регистрирует их рантайм при загрузке. Поэтому
модуль плагина можно импортировать без сервера — так его читает компилятор и тесты.

```python
from amxpy import Plugin

plugin = Plugin(
    "VIP",                       # название в amxpy list и логах
    version="1.2.0",
    author="you",
    description="VIP-бонусы и API для Pawn",
    url="https://example.com",
)
```

Название, версия и остальные метаданные должны быть строками-литералами: компилятор берёт их
из исходника, не запуская код (иначе — [`AMX003`](../reference/diagnostics.md#amx003)).

## Что можно объявить

| Декоратор или метод | Что это | Подробнее |
|---|---|---|
| `@plugin.on(events.X)` | обработчик события | [События](events.md) |
| `@plugin.command("/hp")` | команда игрока в чате или консоли | [Команды](commands.md) |
| `@plugin.server_command("amx_x")` | команда консоли сервера и rcon | [Команды](commands.md#server) |
| `@plugin.every(60)` | периодическая задача | [Async и задачи](async.md) |
| `@plugin.native` | натив для Pawn-плагинов | [API для Pawn](../pawn/api.md) |
| `plugin.forward("x", ...)` | свой форвард | [API для Pawn](../pawn/api.md) |
| `@plugin.on_forward("x")` | подписка на форвард Pawn, AMXX или Python | [Форварды в Python](../pawn/forwards.md) |
| `@plugin.on_unload` | код при выгрузке и перезагрузке | [Горячая перезагрузка](hot-reload.md) |

## Большой плагин — пакет из модулей

Когда плагин растёт, он становится папкой. В каждом модуле — свой `Router()` с теми же
декораторами, а корневой `__init__.py` подключает их через `plugin.include(...)`:

=== "vip/__init__.py"

    ```python
    from amxpy import Plugin, events

    from . import api, commands, perks, repo
    from .config import cfg

    plugin = Plugin("VIP", version="1.2.0", author="amxpy")
    plugin.include(cfg, api.router, commands.router, perks.router)
    ```

=== "vip/perks.py"

    ```python
    from amxpy import Router, events

    from .config import cfg
    from .state import vips

    router = Router()


    @router.on(events.PlayerSpawn, post=True)
    def spawn_bonus(e: events.PlayerSpawn) -> None:
        if e.player in vips:
            e.player.health += cfg.hp_bonus
    ```

`include` принимает роутеры и [конфиги](config.md) и возвращает первый аргумент — поэтому
`cfg = plugin.include(Settings())` сохраняет тип конфига для редактора.

Модули пакета импортируются как `amxpy.plugins.<плагин>.<модуль>`; используйте относительный
импорт (`from . import perks`). Остальные файлы пакета — переводы `lang/*.toml` и данные —
попадают в `.amxpy` вместе с кодом. Полный пример — [VIP-система](../examples/vip.md).

## Подготовка — в `Init`, а не при импорте

Код на верхнем уровне модуля выполняется при импорте — и компилятором тоже. Открывать файлы,
соединения и базы там нельзя (компилятор предупредит:
[`AMX301`](../reference/diagnostics.md#amx301)). Для этого есть событие `Init`:

```python
@plugin.on(events.Init)
async def setup(e: events.Init) -> None:
    await table.create()
    if e.hot_reload:
        plugin.log.info("перезагружен на лету")
```

## Лог

`plugin.log` — обычный `logging.Logger`, который пишет в лог сервера с именем плагина:

```python
plugin.log.info("VIP загружено: %d", len(vips.values()))
plugin.log.warning("база недоступна, пробую ещё раз")
```

Исключение в обработчике не роняет сервер: оно попадает в лог с трассировкой, а счётчик
ошибок плагина виден в `amxpy list`.

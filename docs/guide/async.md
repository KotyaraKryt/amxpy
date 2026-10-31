# Async и задачи

Рантайм amxpy крутит цикл asyncio прямо в игровом кадре: async-обработчики, `await sleep(...)`
и сетевые запросы работают, не задерживая сервер. Сервер не ждёт ваш код — ваш код ждёт,
не мешая серверу.

## Подождать

```python
from amxpy import sleep


@plugin.on(events.PutInServer)
async def greet(e: events.PutInServer) -> None:
    player = e.player
    await sleep(3)
    player.print("!gДобро пожаловать!")
```

`sleep` — это `asyncio.sleep`. Пока обработчик ждёт, сервер обрабатывает кадры как обычно.

## Задачи и их отмена

```python
async def countdown(player: Player) -> None:
    for n in range(5, 0, -1):
        player.center(f"Старт через {n}")
        await sleep(1)


@plugin.command("/race")
def race(player: Player) -> None:
    plugin.spawn(countdown(player))
```

| Задача | Отменяется |
|---|---|
| async-обработчик события игрока или команды | при выходе игрока, выгрузке или перезагрузке плагина |
| `plugin.spawn(...)` из такого обработчика | так же |
| `plugin.spawn(...)` из остального кода | при выгрузке или перезагрузке плагина |

Поэтому `await sleep(60)` перед `player.print(...)` безопасен: если игрок ушёл, до `print`
дело не дойдёт.

## Периодически

```python
@plugin.every(60)
def advert() -> None:
    server.print("!gСайт сервера: !texample.com")


@plugin.every(5, delay=0)        # первый запуск сразу
async def sync() -> None: ...
```

Задача работает, пока работает плагин; может быть async.

## Блокирующий код

Синхронная сеть, `time.sleep` или `sqlite3` остановили бы весь сервер. Компилятор найдёт такие
вызовы в обработчиках и подскажет замену ([`AMX103`](../reference/diagnostics.md#amx103)).

=== "async-библиотеки"

    ```python
    import aiohttp

    async with aiohttp.ClientSession() as session:
        async with session.get("https://example.com/api") as resp:
            data = await resp.json()
    ```

=== "offload — в поток"

    ```python
    import requests

    resp = await plugin.offload(requests.get, "https://example.com/api")
    ```

    Функция выполняется в отдельном потоке, а обработчик ждёт результат, не задерживая кадр.

Для базы данных есть готовая [`Table`](data.md) — её запросы уже идут вне игрового потока.

## Дождаться события

```python
e = await plugin.wait_for(events.RoundEnd, timeout=180)
```

`wait_for` возвращает копию полей следующего подходящего события; `check=` отбирает нужное,
по `timeout` — `TimeoutError`. Пример — в [Событиях](events.md#дождаться-события).

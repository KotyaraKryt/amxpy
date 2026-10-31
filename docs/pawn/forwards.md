# Форварды Pawn в Python

`@plugin.on_forward("имя")` принимает форварды любого источника:

- Pawn-плагинов — `CreateMultiForward` + `ExecuteForward`;
- ядра AMXX — `client_putinserver`, `plugin_cfg` и другие;
- Python-плагинов — объявленные через [`plugin.forward`](api.md#форварды).

```python
from amxpy import Player, Plugin, amxx, server

plugin = Plugin("Jail bridge")


@plugin.on_forward("jb_day_start")
def day_start(day: int, title: str, warden: Player | None) -> int:
    server.print(f"!gДень {day}: !t{title}")
    return 0                                   # ответ форварда


@plugin.on_forward("jb_give_money")
def give_money(player: Player, amount: amxx.Ref) -> None:
    amount.value *= 2                          # параметр по ссылке вернётся в Pawn
```

## Аргументы и ответ

Аргументы разбираются по аннотациям:

| Аннотация | Pawn |
|---|---|
| `int`, `bool` | ячейка |
| `float` | `Float:` |
| `str` | строка |
| `Player` / `Player \| None` | индекс игрока; `None` — 0 или вышедший игрок |
| `amxx.Ref` / `amxx.FloatRef` | параметр по ссылке: `.value` вернётся в Pawn |
| без аннотации | число |

Возвращённое число — ответ форварда (`PLUGIN_HANDLED` = 1). Если подписчиков несколько,
Pawn получит наибольший ответ.

## Со следующей карты

Форварды Pawn и ядра доходят до Python через плагин-приёмник
`addons/amxmodx/plugins/amxpy_forwards.amxx`: amxpy генерирует его сам, с `public` на каждое
имя подписки, и подключает через `configs/plugins-amxpy.ini`.

!!! warning "Новая подписка работает со следующей карты"
    AMXX загружает плагины при смене карты. Добавили `@plugin.on_forward("x")` и поставили
    плагин на сервер — форвард `x` начнёт приходить после смены карты. Форварды других
    Python-плагинов приходят сразу.

## В тестах

```python
def test_day_start(server: FakeServer) -> None:
    server.load("plugins/jail_bridge.py")
    server.change_map()                                   # приёмник загружается с картой
    assert server.pawn_forward("jb_day_start", 3, "Свободный день", 0) == 0
```

`server.pawn_forward` ведёт себя как `ExecuteForward` в Pawn-плагине; `amxx.Ref` и
`amxx.FloatRef` после вызова содержат то, что записал Python.

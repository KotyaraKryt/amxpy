# Игроки и сервер

## Хэндл игрока

`Player` — хэндл одного подключения: слот плюс userid. На одно подключение — один объект:
события, команды и нативы отдают его же, поэтому игрока можно класть в словари и множества и
сравнивать через `is`.

```python
player.print(f"!gПривет, !t{player.name}")
player.health += 25
player.money = min(player.money + 1000, 16000)
if player.team == Team.CT and player.has_access(Access.KICK):
    ...
```

| Свойство | Тип | |
|---|---|---|
| `name`, `steam_id`, `ip` | `str` | SteamID — после события `Authorized` |
| `health`, `armor`, `money`, `frags`, `deaths` | `int` | можно менять |
| `alive`, `bot`, `connected` | `bool` | |
| `team` | `Team` | `T`, `CT`, `SPECTATOR`, `UNASSIGNED` |
| `flags` | `Access` | флаги из `users.ini` |
| `language` | `str` | язык игрока или сервера |

Методы: `print` (чат), `console`, `center`, `command` (выполнить у клиента), `kick`, `tr`
(перевод), `has_access`, `is_teammate`, `info` (setinfo). Полный список —
в [справочнике](../reference/player.md).

!!! warning "Игрок вышел — хэндл «протух»"
    После выхода любое обращение к хэндлу — `StaleHandleError`, а не действие над тем, кто
    занял тот же слот. Если код может пережить игрока (`await`, таймер), проверьте
    `player.connected`. Задачи, запущенные из обработчиков игрока, отменяются при его выходе
    сами.

## Данные плагина по игрокам

`PlayerState` — словарь «игрок → значение», который сам чистится при выходе игрока:

```python
from amxpy import PlayerState

kills: PlayerState[int] = PlayerState(int)            # значение по умолчанию — 0


@plugin.on(events.PlayerKilled, post=True)
def count(e: events.PlayerKilled) -> None:
    if e.killer is not None:
        kills[e.killer] += 1


@plugin.command("/kills")
def show(player: Player) -> None:
    player.print(f"Убийств: !g{kills[player]}")
```

- `PlayerState(factory)` создаёт значение при первом обращении: `int`, `list`, ваш класс;
- `keep=True` переносит данные через [горячую перезагрузку](hot-reload.md);
- `get`, `pop`, `items`, `values`, `clear` и `player in state` — как у словаря.

## Сервер { #server }

`server` — сервер целиком:

```python
from amxpy import server

server.print(f"!gКарта: !t{server.map}")       # чат всем
for player in server.players:                  # только подключённые
    player.money += 1000

bob = server.find_player("#12")                # #userid, SteamID или часть ника
server.set_cvar("mp_freezetime", 3)
server.command("sv_restart 1")                 # выполнится в начале следующего кадра
server.change_level("de_inferno")
```

`server.map`, `server.max_players`, `server.time` — текущая карта, число слотов и игровое время.

## Сущности

Поля вроде `e.grenade`, `e.bomb`, `e.box` возвращают `Entity` — хэндл сущности по индексу
edict с `classname` и `valid`. Менять сущности пока можно только через
[нативы AMXX](../pawn/amxx-call.md): `amxx.call("set_pev", ...)`, `amxx.call("rg_...", ...)`.

# Команды

Команда — функция с декоратором `@plugin.command(...)`. Первый параметр — игрок, который её
вызвал; остальные amxpy разбирает из аргументов по аннотациям и сам строит подсказку
использования и сообщения об ошибках.

```python
from amxpy import Access, Player, Plugin

plugin = Plugin("Admin heal")


@plugin.command("amx_heal", access=Access.SLAY, help="Вылечить игрока")
def heal(admin: Player, target: Player, amount: int = 100) -> None:
    target.health = min(target.health + amount, 255)
    admin.console(f"{target.name}: +{amount} HP")
```

`amx_heal Bob 50` вылечит Bob на 50, `amx_heal Bob` — на 100, а `amx_heal` без аргументов
ответит `Использование: amx_heal <target> [amount]`.

## Чат или консоль

Имя определяет, где работает команда:

| Имя | Где | Пример |
|---|---|---|
| начинается с `/` или `!` | в чате (`say` и `say_team`) | `/hp`, `!rtv` |
| остальные | в консоли игрока | `amx_heal`, `vip_menu` |

Несколько имён — синонимы: `@plugin.command("/hp", "!hp")`. Чат-команда по умолчанию не
показывается в чате (`hide=True`).

## Аргументы

| Аннотация | Что принимает | Ошибка игроку |
|---|---|---|
| `str` | слово или `"строку в кавычках"` | — |
| `int` / `float` | число | `amount: нужно целое число` |
| `bool` | `1`/`0`, `on`/`off`, `yes`/`no`, `true`/`false`, `да`/`нет`, `вкл`/`выкл` | `enabled: нужно on/off` |
| `Player` | ник или его часть, `#userid`, SteamID | `Игрок не найден: Bo` |
| `Enum` | имя или значение члена | `mode: одно из easy/hard` |
| `Literal["a", "b"]` | один из вариантов | `side: одно из t/ct` |
| `X \| None` или значение по умолчанию | необязательный аргумент | — |
| `*rest: str` | остаток строки целиком | — |

```python
from typing import Literal


@plugin.command("/team")
def team(player: Player, side: Literal["t", "ct"]) -> None: ...


@plugin.command("amx_psay", access=Access.CHAT)
def psay(admin: Player, target: Player, *text: str) -> None:
    target.print(f"!t{admin.name}!y: {' '.join(text)}")
```

Ошибки показываются игроку на его языке (русский или английский), а исключение внутри
обработчика — коротким «Ошибка команды, подробности в логе сервера.» и полной трассировкой в логе.

## Доступ и кулдаун

```python
@plugin.command("/rtv", cooldown=30)                    # не чаще раза в 30 секунд на игрока
def rtv(player: Player) -> None: ...


@plugin.command("amx_slap2", access=Access.SLAY | Access.KICK)
def slap(admin: Player, target: Player) -> None: ...
```

`access` — флаги из `users.ini`: без них игрок получит «У вас нет доступа к этой команде.»
Все флаги — в [`Access`](../reference/player.md#amxpy.Access); проверить флаги вручную —
`player.has_access(Access.BAN)`.

## Async-команды

Команда может быть `async` — например, чтобы спросить игрока через меню или сходить в базу:

```python
@plugin.command("/vote")
async def vote(player: Player) -> None:
    choice = await Menu.ask(player, "Какая карта лучше?", ["de_dust2", "de_inferno"], timeout=15)
    if choice is not None:
        server.print(f"!g{player.name}!y голосует за карту №{choice + 1}")
```

## Команды сервера { #server }

`@plugin.server_command` — команда консоли сервера и rcon, без игрока. Аргументы разбираются
так же:

```python
@plugin.server_command("amx_give_money", help="Дать денег игроку")
def give_money(target: Player, amount: int = 1000) -> None:
    target.money = min(target.money + amount, 16000)
    server.console(f"{target.name}: +${amount}")
```

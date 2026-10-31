# События

Обработчик события — функция с декоратором `@plugin.on(...)`. Она получает объект события:
читает его поля, а в **pre**-фазе может менять их, отменить действие игры или ответить за неё.
Все 26 событий с полями — в [справочнике](../reference/events.md).

```python
from amxpy import Plugin, events

plugin = Plugin("No fall damage")
DMG_FALL = 1 << 5


@plugin.on(events.TakeDamage)
def no_fall(e: events.TakeDamage) -> None:
    if e.damage_type & DMG_FALL:
        e.cancel()           # падение не ранит
    elif e.attacker is not None and e.attacker.is_teammate(e.victim):
        e.damage /= 2        # по своим — вполовину
```

## pre и post

=== "pre — до игры"

    Действие ещё не случилось. Можно:

    - менять изменяемые поля — `e.damage *= 2`;
    - отменить действие — `e.cancel()`;
    - ответить за игру у событий с результатом — `return 0` или `e.result = 0`.

    Это фаза по умолчанию: `@plugin.on(events.TakeDamage)`.

=== "post — после игры"

    Игра уже отработала: поля только для чтения, зато видно итог. Подписка — `post=True`:

    ```python
    @plugin.on(events.PlayerKilled, post=True)
    def headshot_bonus(e: events.PlayerKilled) -> None:
        if e.killer is not None and e.headshot:
            e.killer.money += 300
    ```

У части событий есть только одна фаза: например, `FreezeEnd` и `BombPlanted` приходят уже
после действия — для них фаза по умолчанию post. Подписаться на несуществующую фазу не даст
компилятор ([`AMX107`](../reference/diagnostics.md#amx107)).

## Отмена, ответ и остановка

| | Что делает | Где можно |
|---|---|---|
| `e.cancel()` | отменить действие игры | pre, у событий с меткой `cancel()` |
| `return x` / `e.result = x` | ответить за игру | pre, у событий с меткой `result` |
| `e.stop()` | не звать следующие обработчики, в том числе других плагинов | везде |
| `e.cancelled` | отменил ли действие кто-то раньше | везде |

Изменение поля в post, отмена неотменяемого события или запись в поле только для чтения —
ошибки, которые компилятор находит заранее ([`AMX105`, `AMX106`](../reference/diagnostics.md#amx105)).

## Фильтры и приоритет

```python
@plugin.on(events.Say, team=True)            # только say_team
def team_chat(e: events.Say) -> None: ...


@plugin.on(events.TakeDamage, priority=10)   # раньше обработчиков с priority=0
def armor_first(e: events.TakeDamage) -> None: ...
```

Фильтр `поле=значение` вызывает обработчик, только когда поле совпадает. Порядок обработчиков
одного события — по `priority`: больше — раньше.

## Async-обработчики

Обработчик может быть `async`: `await sleep(...)`, запрос к базе или ожидание другого события
не задерживают кадр сервера.

!!! warning "Событие живёт до первого `await`"
    Объект события действителен, пока идёт рассылка. После первого `await` обращение к нему —
    `EventExpiredError`. Нужные поля скопируйте заранее — компилятор подскажет кодом
    [`AMX104`](../reference/diagnostics.md#amx104).

    ```python
    @plugin.on(events.PutInServer)
    async def greet(e: events.PutInServer) -> None:
        player = e.player          # хэндл игрока живёт дольше события
        await sleep(3)
        player.print("!gПривет!")
    ```

Задача обработчика игрока отменяется сама, если он вышел. Подробнее — [Async и задачи](async.md).

## Дождаться события

`plugin.wait_for` ждёт следующее событие и возвращает копию его полей:

```python
@plugin.command("/name")
async def ask_name(player: Player) -> None:
    player.print("Напишите что-нибудь в чат")
    try:
        e = await plugin.wait_for(events.Say, check=lambda e: e.player is player, timeout=30)
    except TimeoutError:
        player.print("!tНе дождался")
        return
    player.print(f"Вы написали: !g{e.text}")
```

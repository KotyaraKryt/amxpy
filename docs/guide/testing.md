# Тестирование

`amxpy.testing.FakeServer` — сервер в памяти: тот же рантайм amxpy и тот же компилятор, но
вместо движка — словари, а время виртуальное. Тест на минуту игры выполняется за миллисекунды.

```python title="tests/test_hello.py"
from amxpy.testing import FakeServer


def test_heal(server: FakeServer) -> None:
    server.load("plugins/hello.py")
    admin = server.join("Admin", flags="e")
    bob = server.join("Bob", health=20)
    admin.command("amx_heal Bob 50")
    assert bob.health == 70
```

Фикстура `server` подключается сама после установки amxpy — свежий сервер на каждый тест.

## Игроки

```python
bob = server.join("Bob", team=Team.T, money=5000, flags="t", lang="ru")
bob.say("/hp")                 # True — команда сработала и сообщение скрыто
bob.command("amx_heal Bob")    # консольная команда
bob.last_chat                  # последнее сообщение в чат без цветовых тегов
bob.chat, bob.hud, bob.dhud    # всё, что ему показали
bob.menu                       # текст меню на экране или None
bob.select(1)                  # нажать клавишу в меню
bob.disconnect()
```

`join` проводит игрока через `Connect` → `PutInServer` → `Authorized` (на следующем кадре).
Свойства `health`, `armor`, `money`, `frags`, `deaths`, `team`, `alive` читают то, что сделал плагин.

## Игра

| Метод | Событие |
|---|---|
| `server.damage(victim, 30, attacker=a)` | `TakeDamage`; возвращает урон после плагинов |
| `server.kill(victim, killer, headshot=True)` | `PlayerKilled` |
| `server.spawn(player)` | `PlayerSpawn` |
| `server.round_start()`, `server.round_end(Winner.CT)`, `server.freeze_end()` | раунд |
| `server.buy(player, "awp", price=4750)` | `BuyWeapon`; `False` — плагин запретил |
| `server.give_money(player, 300)`, `server.drop(...)`, `server.rename(...)`, `server.choose_team(...)` | деньги, выброс, ник, команда |
| `server.throw_grenade(...)`, `server.plant_bomb(...)`, `server.defuse(...)`, `server.explode_bomb()` | гранаты и бомба |
| `server.console("amxpy list")` | строка в консоли сервера |

## Время

```python
server.run(3.5)       # прокрутить 3,5 виртуальные секунды: таймеры, sleep, every
server.settle()       # досчитать задачи и offload(), не двигая время
server.frame()        # один кадр
```

## Нативы, форварды, карта

```python
@server.amxx_native("get_user_name")             # натив AMXX для amxx.call в плагине
def get_user_name(index, name, size):
    name.value = "Bob"
    return len(name.value)

server.change_map()                              # MapEnd → загрузка плагинов → MapStart
server.pawn_forward("jb_day_start", 3, "Свободный день")   # Pawn-плагин вызвал форвард
server.native("vip_is_user_vip", bob)            # вызвать натив плагина, как это сделал бы Pawn
server.forwards                                  # форварды, отправленные в Pawn
```

## Настройки и перезагрузка

```python
server.load("plugins/no_awp.py", cvars={"noawp_admins": 0})
server.set_cvar("hello_delay", 1)
assert server.reload("hello")                    # горячая перезагрузка из исходника
inst = server.plugin("hello")
assert inst.errors == 0                          # исключений в обработчиках не было
```

Все методы — в [справочнике](../reference/testing.md); готовые тесты есть у каждого
[примера](../examples/index.md).

# Меню, HUD и чат

## Чат

```python
player.print("!gЗелёный !tцвет команды !yобычный")
server.print(f"!g{player.name}!y взял бонус")      # всем
player.center("По центру экрана")
player.console("В консоль игрока (~)")
```

| Тег | Цвет в чате |
|---|---|
| `!g` | зелёный |
| `!t` | цвет команды игрока (красный у T, синий у CT) |
| `!y` | обычный |

Расширение VS Code показывает, как будет выглядеть цветная строка, при наведении на неё.

## Меню

`Menu` — меню со страницами: клавиши 1–7 — пункты, 8 и 9 — листать, 0 — выход. Пункты
объявляются декоратором; функция пункта получает игрока, который его выбрал.

```python
from amxpy import Menu, Player

shop = Menu("Магазин")


@shop.item("Аптечка !y(+25 HP)", enabled=lambda p: p.alive)
def medkit(player: Player) -> None:
    player.health = min(player.health + 25, 100)


@shop.item("Броня !y($1000)", enabled=lambda p: p.money >= 1000)
def armor(player: Player) -> None:
    player.money -= 1000
    player.armor = 100


@shop.item(lambda p: f"Ваш ник: !y{p.name}")      # текст — функция от игрока
def whoami(player: Player) -> None: ...


@plugin.command("/shop")
def open_shop(player: Player) -> None:
    shop.show(player)
```

- `enabled` — пункт виден, но серый и не выбирается; `visible` — пункт скрыт;
- `menu.add(title, callback, data=...)` — пункт без декоратора, например в цикле;
- `Menu(title, per_page=7, exit=True, timeout=None)` — пунктов на странице, пункт «Выход»,
  автозакрытие через `timeout` секунд.

Теги цвета в меню свои: `!y` жёлтый, `!w` белый, `!r` красный, `!d` серый, `!R` — выравнивание
по правому краю.

### Дождаться выбора

В async-коде меню можно не описывать обработчиками, а дождаться ответа:

```python
@plugin.command("/vote")
async def vote(player: Player) -> None:
    maps = ["de_dust2", "de_inferno", "de_nuke"]
    choice = await Menu.ask(player, "Какая карта лучше?", maps, timeout=15)
    if choice is None:                     # выход, тайм-аут, другое меню или игрок вышел
        player.print("!tГолосование отменено")
    else:
        server.print(f"!g{player.name}!y выбрал !t{maps[choice]}")
```

`Menu.ask` возвращает номер варианта с нуля, а `await menu.choose(player)` — выбранный
`MenuItem` готового меню (с его `.data`).

## HUD и DHUD

=== "Hud — обычный"

    ```python
    from amxpy import Hud

    info = Hud(y=0.25, color=(0, 200, 255), hold=4)
    info.show(player, f"Здоровье: {player.health}\nБроня: {player.armor}")
    info.clear(player)
    ```

    До 479 байт, 4 канала: сообщения одного канала заменяют друг друга. Без `channel=` каждый
    `Hud` берёт следующий канал по кругу.

=== "DirectorHud — крупный"

    ```python
    from amxpy import DirectorHud

    banner = DirectorHud(y=0.3, color=(255, 140, 0), hold=5)
    banner.show_all("Бомба заложена!")
    ```

    Крупный текст до 127 байт, на экране до 8 сообщений одновременно.

Общие параметры: `x` и `y` (0–1, `-1` — по центру), `color`, `effect` (0 — появление,
1 — мерцание, 2 — печать по буквам), `fade_in`, `fade_out`, `hold`. В VS Code у `color=(r, g, b)`
появляется палитра.

## Сообщения клиенту

Для всего остального — `Message`: user-сообщение собирается целиком и уходит одним вызовом,
незакрытого `message_begin` не бывает.

```python
from amxpy import Message

with Message("ScreenFade", to=player) as m:      # красная вспышка
    m.short(4096).short(4096).short(0)
    m.byte(255).byte(0).byte(0).byte(100)
```

Методы `byte`, `char`, `short`, `long`, `angle`, `coord`, `string`, `entity` — как `WRITE_*`
в Pawn. Без `to=` сообщение уходит всем.

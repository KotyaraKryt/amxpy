# Первый плагин

За пять минут: проект, плагин, тест и установка на сервер без его перезапуска.

## 1. Проект

```bash
amxpy init my-plugins --docker cs16-dev --game /mnt/server/cstrike --port 27015
cd my-plugins
```

`amxpy init` создаёт папку проекта:

```text
my-plugins/
├─ plugins/hello.py        пример плагина
├─ tests/test_hello.py     тест к нему
├─ .vscode/                подсказки, проверка кода, задачи и сниппеты
└─ pyproject.toml          где плагины и куда их ставить
```

Параметры `--docker`, `--game` и `--port` записываются в `[tool.amxpy.server]` — оттуда их берёт
`amxpy deploy`. Без Docker укажите только `--game` с локальным путём к `cstrike`. Подробнее —
[Проект и деплой](project.md).

## 2. Плагин

Плагин — обычный модуль Python с одним объектом `Plugin`. Откройте `plugins/hello.py`:

```python title="plugins/hello.py"
from amxpy import Config, Player, Plugin, cvar, events, sleep

plugin = Plugin("Hello", version="0.1.0")


class Settings(Config, prefix="hello_"):
    delay: float = cvar(3.0, "Задержка приветствия, сек", min=0)


cfg = plugin.include(Settings())


@plugin.on(events.PutInServer)
async def greet(e: events.PutInServer) -> None:
    player = e.player  # событие живёт до первого await — игрока берём заранее
    await sleep(cfg.delay)
    player.print(f"!gПривет, !t{player.name}!y! Набери !g/hp")


@plugin.command("/hp", help="Показать здоровье")
def hp(player: Player) -> None:
    player.print(f"HP: {player.health}, броня: {player.armor}")
```

Что здесь происходит:

- `Settings` — группа cvar'ов: на сервере появится `hello_delay`, а в
  `addons/amxpy/configs/hello.cfg` — строка с описанием. Подробнее — [Настройки и cvar'ы](../guide/config.md).
- `@plugin.on(events.PutInServer)` — обработчик входа игрока. Он async: `await sleep(...)` ждёт,
  не задерживая кадр сервера, а если игрок выйдет раньше, задача отменится сама.
  Подробнее — [События](../guide/events.md) и [Async и задачи](../guide/async.md).
- `@plugin.command("/hp")` — команда в чате. Первый параметр — игрок, который её написал;
  остальные аргументы amxpy разобрал бы по аннотациям. Подробнее — [Команды](../guide/commands.md).
- `!g`, `!t`, `!y` — цвета чата: зелёный, цвет команды, обычный.

## 3. Тест

```python title="tests/test_hello.py"
def test_greets_after_delay(server: FakeServer) -> None:
    server.load(PLUGIN)
    bob = server.join("Bob")
    server.run(3.5)                       # виртуальные 3,5 секунды
    assert "Привет, Bob" in bob.last_chat
```

```bash
pytest
```

Фикстура `server` — это сервер в памяти с тем же рантаймом amxpy: игроки, урон, раунды и время
в нём ненастоящие, а плагин — настоящий. Подробнее — [Тестирование](../guide/testing.md).

## 4. На сервер

```bash
amxpy deploy
```

`deploy` проверяет и собирает плагин, кладёт пакет на сервер, дописывает его в `plugins.ini` и
загружает его по RCON — или перезагружает, если он уже работает. Игроки остаются на сервере.
Если новая версия не запустится, сервер вернёт прежнюю.

!!! tip "В VS Code — одной кнопкой"
    Над `Plugin(...)` есть кнопка **«Установить на сервер»**, а Ctrl+Shift+B собирает проект
    с переходом к ошибкам. Подробнее — [VS Code](vscode.md).

## Дальше

<div class="ax-cards" markdown>
<a class="ax-card" href="../../guide/events/"><b>События</b><span>pre и post, отмена, изменение полей, фильтры</span></a>
<a class="ax-card" href="../../guide/commands/"><b>Команды</b><span>Аргументы из аннотаций, доступ, кулдаун</span></a>
<a class="ax-card" href="../../examples/"><b>Примеры</b><span>Готовые плагины с тестами</span></a>
</div>

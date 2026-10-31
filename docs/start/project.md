# Проект и деплой

Проект amxpy — папка с `pyproject.toml`, плагинами и тестами. Утилита `amxpy` собирает плагины,
ставит их на сервер и общается с ним по RCON. Все параметры команд — в [справочнике](../reference/cli.md).

## Настройки

```toml title="pyproject.toml"
[tool.amxpy]
plugins = "plugins"            # где лежат плагины
out = "dist"                   # куда собирать

[tool.amxpy.server]            # для deploy и rcon
game = "/mnt/server/cstrike"   # папка мода на сервере
docker = "cs16-dev"            # контейнер; без него game — локальная папка
port = 27015
```

Пароль RCON в проект не пишется: он берётся из переменной `AMXPY_RCON_PASSWORD`, а если её нет —
из `rcon_password` в `server.cfg` настроенного сервера.

## Плагин: файл или пакет

=== "Один файл"

    ```text
    plugins/hello.py
    ```

    Для небольших плагинов. Имя плагина — имя файла.

=== "Пакет"

    ```text
    plugins/vip/
    ├─ __init__.py       Plugin(...) и подключение модулей
    ├─ perks.py          router = Router() с обработчиками
    ├─ commands.py
    └─ lang/ru.toml      переводы и другие файлы данных
    ```

    Для больших: модули подключаются через `plugin.include(...)`, файлы рядом попадают
    в пакет. Подробнее — [Плагин и модули](../guide/plugin.md).

## Сборка

```bash
amxpy build                 # все плагины проекта
amxpy build plugins/vip     # один плагин
amxpy build --release       # без исходников в пакете, optimize=2
amxpy build --werror        # предупреждения тоже останавливают сборку
```

Компилятор amxpyc проверяет каждый плагин по исходникам — декларации, поля событий, сигнатуры
нативов — и собирает пакет:

| Что | Где |
|---|---|
| пакет плагина | `dist/<плагин>.amxpy` |
| `.inc` для Pawn-плагинов (если есть нативы или форварды) | `dist/include/<плагин>.inc` |
| конфиг cvar'ов с описаниями | `dist/configs/<плагин>.cfg` |

Ошибки выводятся как `файл:строка:колонка: ошибка AMX101: …` — список кодов в
[диагностиках](../reference/diagnostics.md).

## Установка на сервер

```bash
amxpy deploy                         # собрать и поставить все плагины
amxpy deploy plugins/vip/perks.py    # только плагин, которому принадлежит файл
```

`deploy` собирает плагины, копирует пакеты в `addons/amxpy/plugins/` (через `docker cp`, если
задан контейнер), дописывает новые в `addons/amxpy/plugins.ini` и по RCON выполняет
`amxpy load` или `amxpy reload`. Сгенерированные `.inc` уходят в `addons/amxmodx/scripting/include/`.

## Консоль сервера

```bash
amxpy rcon "amxpy list"
```

| Команда | Что делает |
|---|---|
| `amxpy list` | плагины, их версии и состояние |
| `amxpy version` | версии модуля и Python |
| `amxpy load <файл>` | загрузить пакет |
| `amxpy unload <имя>` | выгрузить плагин |
| `amxpy reload <имя>` | перезагрузить на лету |
| `amxpy_hotreload 0 \| 1 \| 2` | перезагрузка: выключена / по команде (по умолчанию) / сама при изменении файла |

Как устроена перезагрузка и что переживает её — в [Горячей перезагрузке](../guide/hot-reload.md).

# Установка

amxpy состоит из двух частей: модуля AMX Mod X на сервере и Python-пакета на вашей машине,
которым вы пишете, проверяете и ставите плагины.

## Что нужно серверу

| Компонент | Зачем |
|---|---|
| Linux, 32-битный HLDS или [ReHLDS](https://github.com/rehlds/ReHLDS) | на нём запускается всё остальное |
| [Metamod-R](https://github.com/rehlds/Metamod-R) или Metamod | загружает AMX Mod X |
| [AMX Mod X](https://github.com/alliedmodders/amxmodx) 1.9 или новее | загружает модуль amxpy |
| [ReGameDLL](https://github.com/rehlds/ReGameDLL_CS) | игровые события: спавн, урон, раунды, покупки, бомба |

Без ReGameDLL работают плагины, команды, чат, меню, HUD и события подключения, но не игровые
события. Смена ника требует API ReGameDLL 5.3+, гранаты и бомба — 5.5+.

## Модуль на сервер

1. Соберите архив: `scripts/package.sh` → `dist/amxpy-<версия>-linux-i386.tar.gz`.
   Как собрать рантайм и модуль — в разделе «Сборка из исходников» README репозитория amxpy.
2. Распакуйте архив в папку мода `cstrike/`.
3. Добавьте строку `amxpy` в `cstrike/addons/amxmodx/configs/modules.ini`.
4. Перезапустите сервер и проверьте в консоли:

    ```text
    amxpy version
    ```

Плагины лежат в `cstrike/addons/amxpy/plugins/` (пакеты `.amxpy`), а их список — в
`cstrike/addons/amxpy/plugins.ini`. Руками туда ничего класть не нужно: это делает
[`amxpy deploy`](project.md).

!!! tip "Сервер в Docker"
    Для контейнера шаги 2–4 выполняет `scripts/deploy-docker.sh <контейнер> <путь к cstrike>`.
    Исходный `modules.ini` он сохраняет в `build/deploy-backup/`.

## Пакет для разработки

Нужен **Python 3.14**: байткод плагинов привязан к версии CPython, а на сервере работает именно 3.14.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '/путь/к/amxpy[dev]' --config-settings editable_mode=compat
amxpy --help
```

`[dev]` добавляет pytest и flake8. `editable_mode=compat` нужен для подсказок: обычная
editable-установка подключает пакет import hook'ом, который Pylance не видит. Если забыли —
`amxpy init` заметит это и напишет команду для переустановки.

!!! tip "Окружение — внутри проекта"
    Создавайте `.venv` в папке проекта: тогда `amxpy init` пропишет интерпретатор как
    `${workspaceFolder}/.venv/...`, и настройки VS Code будут работать на любой машине.

Вместе с пакетом ставятся:

- утилита `amxpy` — проект, сборка, установка на сервер и RCON ([команды](../reference/cli.md));
- компилятор amxpyc — проверяет плагин до запуска ([диагностики](../reference/diagnostics.md));
- `amxpy.testing` и фикстура pytest `server` — сервер в памяти для тестов ([тестирование](../guide/testing.md)).

Дальше — [первый плагин](first-plugin.md).

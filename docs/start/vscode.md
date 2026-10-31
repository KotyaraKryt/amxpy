# VS Code

`amxpy init` настраивает `.vscode/` в проекте, а расширение amxpy добавляет то, чего нет в
обычном Python: подсказки по нативам AMXX, заготовки после декоратора и установку на сервер.
В существующие файлы настроек `init` только дописывает недостающее.

## Что настраивает проект

- **Подсказки и проверка типов** — Pylance в режиме `standard`. Поля событий и свойства игрока
  типизированы (`e.damage: float`, `e.attacker: Player | None`, `player.health: int`), а
  `plugin.include(Settings())` возвращает ваш конфиг с типами cvar'ов.
- **Ошибки amxpyc при открытии и сохранении** — расширение Flake8 с плагином amxpy: `AMX101`
  «нет такого поля», `AMX104` «событие после await», `AMX103` «блокирующий вызов» и
  [остальные](../reference/diagnostics.md). Модуль пакета проверяется вместе со всем плагином.
- **Автоимпорт** — `python.analysis.autoImportCompletions`: набираете `cycle` или `Menu`,
  выбираете вариант из подсказки — `from itertools import cycle` появляется сам, а имена amxpy
  дописываются в уже существующую строку `from amxpy import ...`.
- **Ошибки, которых не видно глазами** — кроме кодов amxpyc Flake8 показывает неиспользуемый
  импорт (`F401`), повторное определение имени (`F811`) и переменную, которой присвоили, но не
  использовали (`F841`) — частая ошибка, когда в функции забыли `global` или `список[:] = ...`.
- **Задачи** — ++ctrl+shift+b++ собирает с переходом к ошибкам; ещё «установить этот плагин на
  сервер», «перезагрузить плагин на сервере», «плагины на сервере», «тесты».
- **Сниппеты** — `amxplugin`, `amxon`, `amxcmd`, `amxadmin`, `amxnative`, `amxforward`, `amxcfg`,
  `amxmenu`, `amxevery`, `amxstate`, `amxtest`.

VS Code сам предложит расширения Python, Pylance и Flake8 из `extensions.json`. Интерпретатор —
тот, которым запущен `amxpy init`.

## Расширение amxpy

Ставится из репозитория amxpy:

```bash
scripts/build-vscode.sh
code --install-extension dist/amxpy-vscode-0.5.0.vsix
```

### Заготовка после декоратора

Напишите декоратор и нажмите ++enter++ — расширение допишет функцию с курсором на имени:

```python
@plugin.command("/hp")
def hp(player: Player) -> None:      # ← появилось само
    ...

@plugin.on(events.TakeDamage)
def on_take_damage(e: events.TakeDamage) -> None:
    ...
```

То же для `native`, `every`, `item`, `on_change` и остальных. По `@` в начале строки расширение
предлагает заготовки декораторов, а недостающие `Player`, `events`, `Access` дописывает в
`from amxpy import ...`.

### Нативы AMXX

Внутри `amxx.call("…")` работают автодополнение имени натива, документация из `.inc` при
наведении, подсказка параметров и готовый вызов из Python. В индексе — 1400 нативов ядра,
модулей и ReAPI; свои `.inc` добавляются настройкой `amxpy.includePaths` или просто лежат
в проекте. Подробнее о вызове — [Нативы AMXX из Python](../pawn/amxx-call.md).

### Остальное

- палитра для `color=(r, g, b)` у HUD;
- полное имя cvar'а прямо в строке `cvar(...)`;
- предпросмотр цветного чата и меню при наведении на `"!gПривет"`;
- кнопки **«Установить на сервер»** и **«Плагины на сервере»** над `Plugin(...)`.

Всё это можно выключить в настройках: `amxpy.autoDef`, `amxpy.completions`, `amxpy.colors`,
`amxpy.cvarNames`, `amxpy.colorPreview`, `amxpy.codeLens`, `amxpy.nativeHints`.

!!! tip "Настройки можно класть в git"
    В `.vscode/` нет путей вашей машины. Интерпретатор записан как `${workspaceFolder}/.venv/...`
    (если окружение внутри проекта, иначе его выбирают через **Python: Select Interpreter**), а
    amxpy Pylance находит сам, если он установлен с `--config-settings editable_mode=compat`
    ([установка](install.md#пакет-для-разработки)). Старые проекты исправляет повторный
    `amxpy init`: он уберёт прежний путь к amxpy из `python.analysis.extraPaths`.

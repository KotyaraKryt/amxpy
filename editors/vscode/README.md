# amxpy для VS Code

**Нативы для `amxx.call`.** Внутри `amxx.call("` расширение предлагает нативы AMX Mod X 1.10 и ReAPI
(встроенный индекс, ~1400 нативов) и `.inc` вашего проекта. Наведение на имя показывает Pawn-сигнатуру,
описание, параметры, возвращаемое значение и готовый вызов из Python (`amxx.String`, `Ref`, `Array`,
`call_float` — где нужно); при вводе аргументов — подсказка параметров. Свои `.inc` вне проекта —
настройка `amxpy.includePaths`.

**Заготовки по «@».** В начале строки наберите `@` (или `@co`, `@on`…) и выберите:
`@plugin.command`, `@plugin.command admin`, `@plugin.on`, `@plugin.on async`, `@plugin.native`, `@plugin.every`,
`@plugin.server_command`, `@<меню>.item`. Вставляется декоратор вместе с def; имя функции повторяет имя команды
или события и меняется по мере ввода. Роутеры и меню берутся из файла (`plugin`, `router`, `shop`…).

**Палитра цветов.** У `color=(0, 200, 255)` в `Hud` и `DirectorHud` — квадратик цвета; по клику открывается
палитра, выбранный цвет записывается обратно кортежем.

**Имена cvar'ов.** В классе `Config` в конце строки с `cvar(...)` видно полное имя на сервере: `cvar vip_hp_bonus`.

**Предпросмотр цвета.** Наведите на строку с `!g`, `!t`, `!y` в `player.print(...)` или с `!y`, `!r`, `!d` в меню —
подсказка покажет, как текст увидит игрок.

**Установка на сервер.** Над `plugin = Plugin(...)` — кнопки «Установить на сервер» и «Плагины на сервере»; такая же
кнопка в заголовке редактора и команды «amxpy: …» в палитре (Ctrl+Shift+P). Ошибки amxpyc попадают в «Проблемы».
Сервер берётся из `[tool.amxpy.server]` в pyproject.toml.

**Автоимпорт.** Если заготовке нужны `Player`, `events` или `Access`, они дописываются в `from amxpy import ...`.

**def после Enter.** Если декоратор набран вручную, после Enter расширение само дописывает функцию, курсор — на имени:

```python
@plugin.command("/hp")
def hp(player: Player) -> None:
    ...
```

| Декоратор | Заготовка |
|---|---|
| `@plugin.on(events.TakeDamage)` | `def on_take_damage(e: events.TakeDamage) -> None:` |
| `@plugin.command("/hp")` | `def hp(player: Player) -> None:` (с `access=` — `admin: Player`) |
| `@plugin.server_command("amx_x")` | `def amx_x() -> None:` |
| `@plugin.native` | `def plugin_native(player: Player) -> int:` + описание для .inc |
| `@plugin.every(5)` | `def tick() -> None:` |
| `@plugin.on_forward("vip_granted")` | `def on_vip_granted(*args: object) -> None:` |
| `@menu.item("Armor")` | `def armor(player: Player) -> None:` |
| `@cfg.on_change("hp")` | `def on_hp_change(old: int, new: int) -> None:` |

Срабатывает только в файлах, где упоминается amxpy, и не трогает декоратор, под которым def уже есть.
Ctrl+Z убирает заготовку. Каждую возможность можно выключить: `amxpy.autoDef`, `amxpy.completions`, `amxpy.colors`, `amxpy.cvarNames`,
`amxpy.colorPreview`, `amxpy.codeLens`, `amxpy.nativeHints`.

Подсказки по API и ошибки amxpyc дают Pylance и Flake8 — их настраивает `amxpy init`.
Сборка: `scripts/build-vscode.sh` → `dist/amxpy-vscode-<версия>.vsix`.

Встроенный индекс собран из `.inc` AMX Mod X и ReAPI (GPLv3) при сборке расширения.

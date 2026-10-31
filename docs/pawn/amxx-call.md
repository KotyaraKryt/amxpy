# Нативы AMXX из Python

Любой натив ядра AMX Mod X, модуля (cstrike, fun, fakemeta, ReAPI…) или Pawn-плагина
вызывается по имени — без обёрток и без Pawn:

```python
from amxpy import amxx

amxx.call("cs_set_user_money", player, 16000)

name = amxx.String(32)                       # буфер под строку-результат
amxx.call("get_user_name", player, name, 31)
print(name.value)

origin = amxx.Array(3)                       # массив, который заполнит натив
amxx.call("get_user_origin", player, origin)
x, y, z = origin.values

freeze = amxx.call_float("get_cvar_float", "mp_freezetime")
```

## Аргументы

| Python | Pawn |
|---|---|
| `int`, `bool`, `Player` | ячейка (`Player` — индекс игрока) |
| `float` | `Float:` |
| `str` | строка |
| `amxx.String(n)` | буфер `name[]`, который натив заполнит → `.value` |
| `amxx.Ref(x)` / `amxx.FloatRef(x)` | параметр по ссылке `&value` / `&Float:value` → `.value` |
| `amxx.Array(n)` / `amxx.FloatArray(n)` | массив `arr[]` / `Float:vec[]` → `.values` |

Результат `amxx.call` — целое (ячейка). Если натив возвращает `Float:`, используйте
`amxx.call_float`.

!!! warning "Передавайте все параметры"
    Значения по умолчанию из `.inc` подставляет компилятор Pawn, а не сам натив. Поэтому в
    `amxx.call` передаются все параметры по порядку, включая необязательные.

!!! danger "`engclient_cmd` и `amxclient_cmd`: не передавайте пустые аргументы"
    AMXX превращает пустую строку в «аргумента нет», и игра получает вместо `Cmd_Argv(1)`
    `NULL` или мусор. `amxx.call("engclient_cmd", player, "drop", "", "")` роняет сервер:
    ReGameDLL передаёт этот указатель в `DropPlayerItem`. Так же падает и Pawn-плагин с
    `engclient_cmd(id, "drop")`. Передавайте аргумент явно:

    ```python
    amxx.call("engclient_cmd", player, "drop", "weapon_ak47", "")   # второй пустой — можно
    ```

    Команды, подделанные `engclient_cmd`, видит только игра: команды и событие `Say` amxpy
    их не получают — так же, как Pawn-форвард `client_command`.

## Переменное число аргументов

Параметры `any:...` в Pawn передаются по ссылке — оберните числа в `amxx.Ref`:

```python
amxx.call("client_print", 0, 3, "%s: %d", "amxpy", amxx.Ref(42))
```

## Ошибки и проверка

Если натива нет на сервере или он завершился с ошибкой, `amxx.call` бросает
`amxx.NativeError`, а подробности пишет журнал ошибок AMXX. Проверить заранее —
`amxx.available("cs_set_user_money", "rg_give_item")`.

Натив доступен, только если загружен модуль или плагин, которому он принадлежит
(`modules.ini` или Pawn-плагин, которому модуль нужен). Например, без модуля cstrike
нативов `cs_*` не будет.

Нативы, которые регистрируют колбэк вызывающего плагина (`set_task`, `register_event`…),
из Python не работают — для этого у amxpy есть [события](../guide/events.md),
[задачи](../guide/async.md) и [форварды](forwards.md).

## Подсказки в VS Code

Внутри `amxx.call("…")` расширение amxpy дополняет имя натива, показывает его документацию
из `.inc` и готовый вызов из Python. Подробнее — [VS Code](../start/vscode.md#нативы-amxx).

## В тестах

В [FakeServer](../guide/testing.md) настоящих нативов нет — подставьте свой:

```python
@server.amxx_native("get_user_name")
def get_user_name(index, name, size):
    name.value = "Bob"
    return len(name.value)
```

## Как это устроено

amxpy собирает крошечный `.amxx` с нужными именами в таблице нативов и просит ядро AMXX
загрузить его. Ядро само находит нативы по имени — как для обычного плагина, а куча этого
скрипта хранит строки и массивы на время вызова. Поэтому работает любой натив, который видит
обычный Pawn-плагин.

# VIP-система

Плагин-пакет: VIP-статус из базы, бонусы на спавне и в уроне, команда выдачи, натив и
форвард для Pawn-плагинов и переводы.

```text
examples/plugins/vip/
├─ __init__.py     Plugin и подключение модулей
├─ config.py       cvar'ы
├─ models.py       dataclass Vip
├─ repo.py         хранилище SQLite
├─ state.py        PlayerState(keep=True)
├─ perks.py        загрузка VIP и бонусы
├─ commands.py     /vip и amx_vip_add
├─ api.py          натив и форвард для Pawn
└─ lang/           ru.toml, en.toml
```

=== "\_\_init\_\_.py"

    ```python
    --8<-- "vip/__init__.py"
    ```

=== "perks.py"

    ```python
    --8<-- "vip/perks.py"
    ```

=== "commands.py"

    ```python
    --8<-- "vip/commands.py"
    ```

=== "api.py"

    ```python
    --8<-- "vip/api.py"
    ```

=== "config.py"

    ```python
    --8<-- "vip/config.py"
    ```

=== "models.py"

    ```python
    --8<-- "vip/models.py"
    ```

=== "repo.py"

    ```python
    --8<-- "vip/repo.py"
    ```

=== "state.py"

    ```python
    --8<-- "vip/state.py"
    ```

## Как это работает

- **`__init__.py`** создаёт единственный `Plugin` и подключает роутеры модулей и конфиг через
  `plugin.include(...)`; в `Init` готовит базу.
- **`state.py`** — `vips: PlayerState[Vip]` с `keep=True`: статус игроков переживает горячую
  перезагрузку.
- **`perks.py`** загружает VIP в `Authorized` (SteamID уже известен), даёт HP на спавне
  (post) и усиливает урон (pre).
- **`commands.py`** — `/vip` отвечает на языке игрока через `player.tr(...)`, а
  `amx_vip_add <target> [days]` выдаёт VIP и рассылает форвард `vip_granted`.
- **`api.py`** — натив `vip_is_user_vip`, `vip_days_left` и форвард `vip_granted`: из них
  amxpyc генерирует [`vip.inc`](../pawn/api.md#сгенерированный-inc) для Pawn-плагинов.

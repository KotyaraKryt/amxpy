# Plugin и Router

`Plugin` — корень плагина, `Router` — набор объявлений модуля. Всё, что умеет `Router`,
доступно и у `Plugin`. Руководство: [Плагин и модули](../guide/plugin.md).

::: amxpy.Plugin
    options:
      members: [config_file, keep, kept, on_unload, log]

::: amxpy.Router

::: amxpy.Forward
    options:
      members: [emit]

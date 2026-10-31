# События

Каталог всех событий `amxpy.events`. Метки: **pre**/**post** — фазы, на которые можно
подписаться (первая — фаза по умолчанию), `cancel()` — действие можно отменить,
`result` — можно ответить за игру. Поля с меткой «меняется в pre» можно присваивать
в pre-обработчике. Руководство: [События](../guide/events.md).

<!-- amxpy:events -->

## Объект события

::: amxpy.Event
    options:
      heading_level: 3
      members: [cancel, stop, cancelled, result]

::: amxpy.EventError
    options:
      heading_level: 3

::: amxpy.EventExpiredError
    options:
      heading_level: 3

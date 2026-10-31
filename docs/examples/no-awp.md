# Запрет AWP

Покупка AWP отменяется в pre-фазе `BuyWeapon` — до того, как игра спишет деньги. Админы с
флагом `t` покупать могут, если включён cvar `noawp_admins`.

```python title="examples/plugins/no_awp.py"
--8<-- "no_awp.py"
```

## Как это работает

- `BuyWeapon` требует ReGameDLL; `e.weapon` — имя без префикса `weapon_`: `awp`, `ak47`, `shield`.
- `e.cancel()` в pre — покупки не будет, деньги останутся у игрока.
- `Access.LEVEL_H` — флаг `t` из `users.ini`.

## Что проверяют тесты

```python
server.load(EXAMPLES / "no_awp.py")
bob = server.join("Bob", money=5000)
assert server.buy(bob, "awp", price=4750) is False
assert bob.money == 5000 and bob.last_chat == "AWP на сервере запрещена"
```

Ещё: AK-47 покупается, админ с флагом `t` покупает AWP, а с `noawp_admins 0` — уже нет.

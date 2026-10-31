"""Запрет AWP: покупка отменяется до списания денег, кроме админов с флагом t."""

from amxpy import Access, Config, Plugin, cvar, events

plugin = Plugin("No AWP", version="1.0.0", author="amxpy")


class Settings(Config, prefix="noawp_"):
    admins: bool = cvar(True, "Разрешить AWP админам с флагом t")


cfg = plugin.include(Settings())


@plugin.on(events.BuyWeapon)
def no_awp(e: events.BuyWeapon) -> None:
    if e.weapon != "awp":
        return
    if cfg.admins and e.player.has_access(Access.LEVEL_H):
        return
    e.player.print("!tAWP на сервере запрещена")
    e.cancel()

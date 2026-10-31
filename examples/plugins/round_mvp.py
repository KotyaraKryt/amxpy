"""Лучший игрок раунда: убийства и хедшоты за раунд, итог — крупным HUD и бонусом."""

from amxpy import Config, DirectorHud, Plugin, PlayerState, cvar, events

plugin = Plugin("Round MVP", version="1.0.0", author="amxpy")


class Settings(Config, prefix="mvp_"):
    bonus: int = cvar(500, "Денежный бонус лучшему игроку", min=0, max=16000)


cfg = plugin.include(Settings())
kills: PlayerState[int] = PlayerState(int)
headshots: PlayerState[int] = PlayerState(int)
banner = DirectorHud(y=0.25, color=(198, 244, 50), hold=5)


@plugin.on(events.RoundStart)
def reset(e: events.RoundStart) -> None:
    kills.clear()
    headshots.clear()


@plugin.on(events.PlayerKilled, post=True)
def count(e: events.PlayerKilled) -> None:
    if e.killer is None or e.killer is e.victim:
        return
    kills[e.killer] += 1
    if e.headshot:
        headshots[e.killer] += 1


@plugin.on(events.RoundEnd, post=True)
def announce(e: events.RoundEnd) -> None:
    if not kills.items():
        return
    best, frags = max(kills.items(), key=lambda pair: (pair[1], headshots.get(pair[0], 0)))
    best.money = min(best.money + cfg.bonus, 16000)
    banner.show_all(f"MVP раунда: {best.name} — {frags} убийств, {headshots.get(best, 0)} в голову")

"""Приветствие, /hp, лечение админом и запрет урона по своим."""

from amxpy import Access, Config, Player, Plugin, cvar, events, sleep

plugin = Plugin("Hello", version="1.0.0", author="amxpy")


class Settings(Config, prefix="hello_"):
    delay: float = cvar(3.0, "Задержка приветствия, сек", min=0)
    friendly_fire: bool = cvar(False, "Разрешить урон по своим")


cfg = plugin.include(Settings())


@plugin.on(events.PutInServer)
async def greet(e: events.PutInServer) -> None:
    player = e.player  # событие живёт до первого await, хэндл игрока — дольше
    await sleep(cfg.delay)  # кадр не блокируется; игрок вышел — задача отменится
    player.print(f"!gПривет, !t{player.name}!y! Набери !g/hp")


@plugin.on(events.TakeDamage)
def no_team_damage(e: events.TakeDamage) -> None:
    if not cfg.friendly_fire and e.attacker is not None and e.attacker.is_teammate(e.victim):
        e.cancel()


@plugin.command("/hp", help="Показать здоровье")
def hp(player: Player) -> None:
    player.print(f"HP: {player.health}, броня: {player.armor}")


@plugin.command("amx_heal", access=Access.SLAY, help="Вылечить игрока")
def heal(admin: Player, target: Player, amount: int = 100) -> None:
    target.health = min(target.health + amount, 255)
    admin.console(f"{target.name}: +{amount} HP")

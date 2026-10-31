from amxpy import Router, events

from . import repo
from .api import vip_granted
from .config import cfg
from .state import vips

router = Router()


@router.on(events.Authorized)  # SteamID уже известен
async def load(e: events.Authorized) -> None:
    player = e.player
    vip = await repo.find(player.steam_id)  # кадр не ждёт; игрок ушёл — задача отменится
    if vip is not None and vip.active:
        vips[player] = vip
        vip_granted.emit(player, vip.days_left)


@router.on(events.PlayerSpawn, post=True)
def spawn_bonus(e: events.PlayerSpawn) -> None:
    if e.player in vips:
        e.player.health += cfg.hp_bonus


@router.on(events.TakeDamage)
def more_damage(e: events.TakeDamage) -> None:
    if e.attacker in vips:
        e.damage *= cfg.damage_mult

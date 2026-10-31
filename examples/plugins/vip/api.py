"""То, что видят Pawn-плагины: amxpyc генерирует из этого vip.inc."""

from amxpy import Player, Router

from .state import vips

router = Router()
vip_granted = router.forward("vip_granted", player=Player, days=int)


@router.native
def vip_is_user_vip(player: Player) -> bool:
    """Является ли игрок VIP."""
    return player in vips


@router.native
def vip_days_left(player: Player) -> int:
    """Сколько дней VIP осталось: -1 — навсегда, 0 — не VIP."""
    vip = vips.get(player)
    return vip.days_left if vip else 0

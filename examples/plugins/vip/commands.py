from datetime import UTC, datetime, timedelta

from amxpy import Access, Player, Router

from . import repo
from .api import vip_granted
from .models import Vip
from .state import vips

router = Router()


@router.command("/vip", help="Статус VIP")
def status(player: Player) -> None:
    match vips.get(player):
        case None:
            player.print(player.tr("VIP_NONE"))
        case Vip(until=None):
            player.print(player.tr("VIP_FOREVER"))
        case vip:
            player.print(player.tr("VIP_DAYS", days=vip.days_left))


@router.command("amx_vip_add", access=Access.RCON, help="Выдать VIP")
async def add(admin: Player, target: Player, days: int = 30) -> None:
    vip = Vip(target.steam_id, datetime.now(UTC) + timedelta(days=days))
    await repo.save(vip)
    vips[target] = vip
    vip_granted.emit(target, vip.days_left)
    admin.console(f"VIP: {target.name}, {days} d.")

from amxpy.storage import Table

from .models import Vip

table = Table("vip", Vip, key="steam_id")  # addons/amxpy/data/vip.db, запросы вне игрового потока


async def migrate() -> None:
    await table.create()


async def find(steam_id: str) -> Vip | None:
    return await table.get(steam_id)


async def save(vip: Vip) -> None:
    await table.put(vip)

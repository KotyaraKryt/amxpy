"""«С возвращением»: число визитов и дата прошлого захода в SQLite по SteamID."""

from dataclasses import dataclass
from datetime import datetime

from amxpy import Plugin, events
from amxpy.storage import Table

plugin = Plugin("Welcome back", version="1.0.0", author="amxpy")


@dataclass
class Visit:
    steam_id: str
    visits: int
    last_seen: datetime


table = Table("visits", Visit, key="steam_id")


@plugin.on(events.Init)
async def setup(e: events.Init) -> None:
    await table.create()


@plugin.on(events.Authorized)
async def welcome(e: events.Authorized) -> None:
    player, steam_id = e.player, e.steam_id  # событие живёт до первого await
    if player.bot:
        return
    visit = await table.get(steam_id)  # запрос идёт вне игрового потока
    if visit is None:
        player.print(f"!gДобро пожаловать, !t{player.name}!y!")
        visit = Visit(steam_id, 0, datetime.now())
    else:
        player.print(f"!gС возвращением!y! Визит №{visit.visits + 1}, прошлый — !t{visit.last_seen:%d.%m.%Y}")
    visit.visits += 1
    visit.last_seen = datetime.now()
    await table.put(visit)

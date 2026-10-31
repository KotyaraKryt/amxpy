"""VIP-система: бонусы на спавне и в уроне, натив и форвард для Pawn, хранение в SQLite."""

from amxpy import Plugin, events

from . import api, commands, perks, repo
from .config import cfg

plugin = Plugin("VIP", version="1.2.0", author="amxpy")
plugin.include(cfg, api.router, commands.router, perks.router)


@plugin.on(events.Init)
async def init(e: events.Init) -> None:
    hot = e.hot_reload
    await repo.migrate()
    if hot:
        plugin.log.info("reloaded on the fly, player state kept")

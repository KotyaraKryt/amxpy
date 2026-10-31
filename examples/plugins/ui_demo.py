"""Меню, HUD и DHUD: /menu, /hud, /dhud, /vote."""

from amxpy import DirectorHud, Hud, Menu, Player, Plugin, server

plugin = Plugin("UI demo", version="1.0.0", author="amxpy")

info = Hud(y=0.25, color=(0, 200, 255), hold=4.0)
banner = DirectorHud(y=0.3, color=(255, 140, 0), hold=4.0)
maps = ["de_dust2", "de_inferno", "de_nuke"]

shop = Menu("Магазин")


@shop.item("Аптечка !y(+25 HP)", enabled=lambda p: p.alive)
def medkit(player: Player) -> None:
    player.health = min(player.health + 25, 100)
    player.print("!gАптечка использована")


@shop.item("Броня !y(100)", enabled=lambda p: p.alive and p.armor < 100)
def armor(player: Player) -> None:
    player.armor = 100
    player.print("!gБроня выдана")


@shop.item(lambda p: f"Ваш ник: !y{p.name}")
def whoami(player: Player) -> None:
    player.print(f"Вы — !t{player.name}")


for n in range(1, 8):  # ещё пункты, чтобы появилась вторая страница
    shop.add(f"Пункт {n}", lambda p, n=n: p.print(f"Выбран пункт !g{n}"))


@plugin.command("/menu", help="Меню со страницами")
def open_menu(player: Player) -> None:
    shop.show(player)


@plugin.command("/hud", help="Обычный HUD")
def show_hud(player: Player) -> None:
    info.show(player, f"Привет, {player.name}!\nЭто обычный HUD")


@plugin.command("/dhud", help="DHUD для всех")
def show_dhud(player: Player) -> None:
    banner.show_all(f"{player.name} вызвал DHUD")


@plugin.command("/vote", help="Голосование через Menu.ask")
async def vote(player: Player) -> None:
    choice = await Menu.ask(player, "Какая карта лучше?", maps, timeout=15)
    if choice is None:
        player.print("!tГолосование отменено")
    else:
        server.print(f"!g{player.name}!y выбрал !t{maps[choice]}")
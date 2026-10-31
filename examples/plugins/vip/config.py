from amxpy import Config, cvar


class Settings(Config, prefix="vip_"):
    hp_bonus: int = cvar(25, "Доп. HP на спавне", min=0, max=155)
    damage_mult: float = cvar(1.1, "Множитель урона VIP", min=1.0, max=2.0)


cfg = Settings()

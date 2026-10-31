from amxpy import PlayerState

from .models import Vip

# vips[player] — очищается при выходе игрока и переживает горячую перезагрузку
vips: PlayerState[Vip] = PlayerState(keep=True)

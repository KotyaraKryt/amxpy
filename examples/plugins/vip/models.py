from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import ceil


@dataclass
class Vip:
    steam_id: str
    until: datetime | None = None  # None — навсегда

    @property
    def active(self) -> bool:
        return self.until is None or self.until > datetime.now(UTC)

    @property
    def days_left(self) -> int:
        """Сколько дней осталось; -1 — навсегда."""
        if self.until is None:
            return -1
        return max(0, ceil((self.until - datetime.now(UTC)) / timedelta(days=1)))

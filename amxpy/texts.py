"""Сообщения рантайма игрокам (ошибки команд и т.п.) на языке игрока."""

from __future__ import annotations

from typing import Any

MESSAGES: dict[str, dict[str, str]] = {
    "usage": {"en": "Usage: {usage}", "ru": "Использование: {usage}"},
    "no_access": {"en": "You have no access to this command.", "ru": "У вас нет доступа к этой команде."},
    "cooldown": {"en": "Wait {seconds} s.", "ru": "Подождите {seconds} с."},
    "bad_int": {"en": "{name}: a whole number is expected", "ru": "{name}: нужно целое число"},
    "bad_float": {"en": "{name}: a number is expected", "ru": "{name}: нужно число"},
    "bad_bool": {"en": "{name}: expected on/off", "ru": "{name}: нужно on/off"},
    "bad_choice": {"en": "{name}: one of {choices}", "ru": "{name}: одно из {choices}"},
    "player_not_found": {"en": "Player not found: {query}", "ru": "Игрок не найден: {query}"},
    "player_ambiguous": {"en": "Several players match: {query}", "ru": "Под «{query}» подходят несколько игроков"},
    "error": {"en": "Command failed, see the server log.", "ru": "Ошибка команды, подробности в логе сервера."},
    "menu_back": {"en": "Back", "ru": "Назад"},
    "menu_next": {"en": "Next", "ru": "Далее"},
    "menu_exit": {"en": "Exit", "ru": "Выход"},
}


def text(key: str, lang: str, **params: Any) -> str:
    variants = MESSAGES[key]
    return variants.get(lang, variants["en"]).format(**params)

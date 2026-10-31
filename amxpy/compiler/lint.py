"""Плагин flake8: диагностики amxpyc прямо в редакторе.

Расширение Flake8 для VS Code показывает их при открытии и сохранении файла,
если запускает flake8 из окружения с amxpy (``"flake8.importStrategy": "fromEnvironment"``,
так настраивает ``amxpy init``). Коды те же, что печатает ``amxpy build``:
```
flake8 --select=AMX plugins/
```
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from typing import Any

from .build import VERSION, check_file


class Flake8Checker:
    name = "amxpy"
    version = VERSION

    def __init__(self, tree: ast.AST, filename: str, lines: list[str]) -> None:
        # tree не нужен (плагин разбирается целиком), но по нему flake8 узнаёт AST-плагин
        self.filename = filename
        self.text = "".join(lines)

    def run(self) -> Iterator[tuple[int, int, str, type[Any]]]:
        if self.filename in ("stdin", "-"):  # без --stdin-display-name не найти остальные модули плагина
            return
        for d in check_file(self.filename, self.text):
            yield d.line, d.col - 1, f"{d.code} {d.message}", type(self)

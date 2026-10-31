"""Диагностики компилятора."""

from __future__ import annotations

from dataclasses import dataclass

# Предупреждения сборку не останавливают; остальные коды — ошибки
WARNING_CODES = frozenset({"AMX103", "AMX104", "AMX105", "AMX205", "AMX301"})


@dataclass(frozen=True)
class Diagnostic:
    code: str  # AMX101
    severity: str  # "error" | "warning"
    file: str  # путь к исходнику — как его передали компилятору
    line: int
    col: int
    message: str

    def format(self) -> str:
        label = "ошибка" if self.severity == "error" else "предупреждение"
        return f"{self.file}:{self.line}:{self.col}: {label} {self.code}: {self.message}"

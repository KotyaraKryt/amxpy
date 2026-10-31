from __future__ import annotations

import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "plugins"

MakePlugin = Callable[..., Path]


@pytest.fixture
def make_plugin(tmp_path: Path) -> MakePlugin:
    """Исходник плагина во временной папке: ``make_plugin("name", код[, files={...}])``."""
    root = tmp_path / "src"

    def make(name: str, source: str, files: dict[str, str] | None = None) -> Path:
        root.mkdir(exist_ok=True)
        if files is None:
            path = root / f"{name}.py"
            path.write_text(textwrap.dedent(source), encoding="utf-8")
            return path
        package = root / name
        package.mkdir(exist_ok=True)
        (package / "__init__.py").write_text(textwrap.dedent(source), encoding="utf-8")
        for rel, text in files.items():
            target = package / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(text), encoding="utf-8")
        return package

    return make

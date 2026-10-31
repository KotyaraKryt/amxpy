"""pytest-фикстура ``server`` — свежий FakeServer на каждый тест."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from . import FakeServer


@pytest.fixture
def server(tmp_path: Path) -> Iterator[FakeServer]:
    with FakeServer(game_dir=tmp_path) as srv:
        yield srv

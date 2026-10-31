"""Настройки проекта плагинов: ``[tool.amxpy]`` в pyproject.toml.

    [tool.amxpy]
    plugins = "plugins"            # исходники: файлы *.py и папки с __init__.py
    out = "dist"                   # куда собирать пакеты

    [tool.amxpy.server]            # для amxpy deploy и amxpy rcon
    game = "/home/hlds/cstrike"    # папка мода на сервере
    docker = "hlds"                # контейнер Docker; без него game — локальная папка
    host = "127.0.0.1"
    port = 27015

Пароль RCON — переменная окружения ``AMXPY_RCON_PASSWORD``, иначе
``rcon_password`` из ``server.cfg`` сервера: в файлы проекта он не попадает.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_RCON_PASSWORD = re.compile(r'^[ \t]*rcon_password[ \t]+"?([^"\r\n]*)"?', re.MULTILINE)


class ProjectError(Exception):
    """Ошибка настроек проекта или доступа к серверу."""


@dataclass
class Server:
    """Сервер разработки: папка мода локально или в Docker-контейнере."""

    game: str
    docker: str | None = None
    host: str = "127.0.0.1"
    port: int = 27015

    def __str__(self) -> str:
        return f"{self.docker}:{self.game}" if self.docker else self.game

    def read(self, rel: str) -> str | None:
        """Текст файла сервера (путь от папки мода) или None, если его нет."""
        if self.docker:
            run = self._docker("exec", self.docker, "cat", self._path(rel), check=False)
            return run.stdout.decode("utf-8", "replace") if run.returncode == 0 else None
        try:
            return Path(self.game, rel).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return None

    def put(self, src: Path, rel: str) -> None:
        """Положить файл на сервер (путь назначения от папки мода)."""
        if self.docker:
            self._docker("exec", self.docker, "mkdir", "-p", str(PurePosixPath(self._path(rel)).parent))
            self._docker("cp", str(src), f"{self.docker}:{self._path(rel)}")
            return
        dest = Path(self.game, rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)  # сервер не увидит наполовину записанный пакет

    def write(self, rel: str, text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, PurePosixPath(rel).name)
            src.write_text(text, encoding="utf-8")
            self.put(src, rel)

    def rcon_password(self) -> str:
        password = os.environ.get("AMXPY_RCON_PASSWORD")
        if password:
            return password
        found = _RCON_PASSWORD.findall(self.read("server.cfg") or "")
        if not found or not found[-1]:
            raise ProjectError("нет пароля RCON: задайте AMXPY_RCON_PASSWORD или rcon_password в server.cfg")
        return found[-1]

    def _path(self, rel: str) -> str:
        return str(PurePosixPath(self.game, rel))

    def _docker(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
        try:
            run = subprocess.run(["docker", *args], capture_output=True)
        except FileNotFoundError:
            raise ProjectError("не найдена команда docker") from None
        if check and run.returncode != 0:
            raise ProjectError(f"docker {args[0]}: {run.stderr.decode('utf-8', 'replace').strip()}")
        return run


@dataclass
class Project:
    root: Path
    plugins: Path
    out: Path
    server: Server | None = None


def load_project(cwd: Path | None = None) -> Project:
    """Настройки из ближайшего pyproject.toml с ``[tool.amxpy]``; без него — plugins/ и dist/."""
    cwd = (cwd or Path.cwd()).resolve()
    for folder in (cwd, *cwd.parents):
        pyproject = folder / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ProjectError(f"{pyproject}: {exc}") from None
        tool = data.get("tool", {}).get("amxpy")
        if isinstance(tool, dict):
            return _project(folder, tool, pyproject)
    return Project(cwd, cwd / "plugins", cwd / "dist")


def _project(root: Path, tool: dict[str, Any], source: Path) -> Project:
    table = tool.get("server")
    if table is not None and not (isinstance(table, dict) and table.get("game")):
        raise ProjectError(f"{source}: в [tool.amxpy.server] нужен game — папка мода на сервере")
    try:
        server = None
        if table is not None:
            docker = table.get("docker")
            server = Server(
                game=str(table["game"]),
                docker=str(docker) if docker else None,
                host=str(table.get("host", "127.0.0.1")),
                port=int(table.get("port", 27015)),
            )
        return Project(root, root / str(tool.get("plugins", "plugins")), root / str(tool.get("out", "dist")), server)
    except (TypeError, ValueError) as exc:
        raise ProjectError(f"{source}: ошибка в [tool.amxpy]: {exc}") from None

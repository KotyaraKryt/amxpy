from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import threading
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from amxpy.cli import main
from amxpy.compiler import compile_plugin
from amxpy.project import load_project
from amxpy.scaffold import _matcher

from .conftest import EXAMPLES


class FakeRcon:
    """UDP-сервер с RCON GoldSrc, который понимает amxpy list/load/reload."""

    def __init__(self, password: str, loaded: set[str]) -> None:
        self.password = password
        self.loaded = set(loaded)
        self.commands: list[str] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port: int = self.sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _reply(self, command: str) -> str:
        self.commands.append(command)
        words = command.split()
        if words == ["amxpy", "list"]:
            rows = "".join(f"  {name:<16} 0.1.0      running  {name}\n" for name in sorted(self.loaded))
            return f"[amxpy] {len(self.loaded)} plugin(s):\n{rows}"
        if len(words) == 3 and words[:2] in (["amxpy", "load"], ["amxpy", "reload"]):
            verb, name = words[1:]
            ok = (name in self.loaded) == (verb == "reload")
            self.loaded.add(name)
            return f"[amxpy] {verb} {name}: {'ok' if ok else 'failed, see the server log'}\n"
        return f'Unknown command "{words[0]}"\n'

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(4096)
            except TimeoutError:
                continue
            except OSError:
                return
            text = data[4:].decode()
            if text.startswith("challenge rcon"):
                self.sock.sendto(b"\xff\xff\xff\xffchallenge rcon 42\n", addr)
                continue
            match = re.match(r'rcon 42 "([^"]*)" (.*)', text.strip())
            answer = self._reply(match[2]) if match and match[1] == self.password else "Bad rcon_password.\n"
            self.sock.sendto(b"\xff\xff\xff\xffl" + answer.encode(), addr)

    def close(self) -> None:
        self._stop.set()
        self._thread.join()
        self.sock.close()


@pytest.fixture
def fake_rcon(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeRcon]:
    monkeypatch.setattr("amxpy.rcon.TAIL_TIMEOUT", 0.05)
    server = FakeRcon("secret", {"hello"})
    yield server
    server.close()


def _project(root: Path, server: str = "") -> Path:
    """Проект с плагинами hello и vip из примеров, исходники — в src/."""
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text(f'[tool.amxpy]\nplugins = "src"\nout = "out"\n{server}', encoding="utf-8")
    shutil.copy(EXAMPLES / "hello.py", root / "src" / "hello.py")
    shutil.copytree(EXAMPLES / "vip", root / "src" / "vip", ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _game(tmp_path: Path, password: str = "secret") -> Path:
    game = tmp_path / "hlds" / "cstrike"
    (game / "addons" / "amxpy").mkdir(parents=True)
    (game / "server.cfg").write_text(f'hostname "dev"\n// rcon_password "old"\nrcon_password "{password}"\n')
    (game / "addons" / "amxpy" / "plugins.ini").write_text("; plugins\nhello\n")
    return game


def test_build_uses_project_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    root = _project(tmp_path / "proj")
    monkeypatch.chdir(root)
    assert main(["build"]) == 0
    assert (root / "out" / "hello.amxpy").is_file()
    assert (root / "out" / "include" / "vip.inc").is_file()
    assert "→ out/" in capsys.readouterr().out


def test_build_output_matches_vscode_problem_matcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path / "proj")
    perks = root / "src" / "vip" / "perks.py"
    perks.write_text(perks.read_text(encoding="utf-8").replace("e.damage *=", "e.dmg *="), encoding="utf-8")
    line = next(n for n, text in enumerate(perks.read_text(encoding="utf-8").splitlines(), 1) if "e.dmg" in text)
    monkeypatch.chdir(root)
    assert main(["build"]) == 1
    printed = capsys.readouterr().out.splitlines()
    errors = re.compile(_matcher("error", "ошибка")["pattern"]["regexp"])
    warnings = re.compile(_matcher("warning", "предупреждение")["pattern"]["regexp"])
    found = [m.groups() for text in printed if (m := errors.match(text))]
    assert found == [("src/vip/perks.py", str(line), "9", "AMX101", "у TakeDamage нет поля 'dmg' — может быть, damage?")]
    assert not any(warnings.match(text) for text in printed)


def test_init_creates_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    proj = tmp_path / "proj"
    game = tmp_path / "hlds" / "cstrike"
    assert main(["init", str(proj), "--game", str(game), "--port", "27016"]) == 0
    for rel in (
        "pyproject.toml",
        "plugins/hello.py",
        "tests/test_hello.py",
        ".gitignore",
        ".vscode/settings.json",
        ".vscode/tasks.json",
        ".vscode/extensions.json",
        ".vscode/amxpy.code-snippets",
    ):
        assert (proj / rel).is_file(), rel
    server = load_project(proj).server
    assert server is not None and (server.game, server.port, server.docker) == (str(game), 27016, None)

    settings = json.loads((proj / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["flake8.importStrategy"] == "fromEnvironment"
    assert settings["flake8.severity"]["AMX"] == "Error" and settings["flake8.severity"]["AMX104"] == "Warning"
    assert settings["python.analysis.typeCheckingMode"] == "standard"
    assert settings["python.analysis.autoImportCompletions"] is True
    assert settings["flake8.args"] == ["--select=AMX,F401,F811,F841"]
    tasks = json.loads((proj / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    assert {"amxpy: собрать", "amxpy: установить этот плагин на сервер"} <= {t["label"] for t in tasks["tasks"]}
    extensions = json.loads((proj / ".vscode" / "extensions.json").read_text(encoding="utf-8"))
    assert {"ms-python.flake8", "amxpy.amxpy"} <= set(extensions["recommendations"])
    snippets = json.loads((proj / ".vscode" / "amxpy.code-snippets").read_text(encoding="utf-8"))
    assert "TakeDamage" in snippets["amxpy: обработчик события"]["body"][0]
    sample = compile_plugin(proj / "plugins" / "hello.py")
    assert sample.ok and sample.diagnostics == []

    before = {p: p.read_bytes() for p in proj.rglob("*") if p.is_file()}
    capsys.readouterr()
    assert main(["init", str(proj)]) == 0  # повторный запуск ничего не меняет
    assert {p: p.read_bytes() for p in proj.rglob("*") if p.is_file()} == before
    assert not any(line.startswith("  + ") for line in capsys.readouterr().out.splitlines())


def test_init_keeps_user_files(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    vscode = proj / ".vscode"
    vscode.mkdir(parents=True)
    (vscode / "settings.json").write_text(json.dumps({"editor.tabSize": 2, "flake8.args": ["--max-line-length=100"]}))
    (vscode / "tasks.json").write_text('{\n    // мои задачи\n    "version": "2.0.0",\n    "tasks": []\n}\n')
    (proj / "pyproject.toml").write_text('[project]\nname = "my-plugins"\n')
    assert main(["init", str(proj)]) == 0

    settings = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))
    assert settings["editor.tabSize"] == 2
    assert settings["flake8.args"] == ["--max-line-length=100"]  # своё значение не перетираем
    assert settings["flake8.importStrategy"] == "fromEnvironment"
    assert "// мои задачи" in (vscode / "tasks.json").read_text(encoding="utf-8")  # JSONC не трогаем
    data = tomllib.loads((proj / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "my-plugins" and data["tool"]["amxpy"]["plugins"] == "plugins"


def test_init_sample_test_passes(tmp_path: Path) -> None:
    proj = tmp_path / "proj"
    assert main(["init", str(proj)]) == 0
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=proj,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "2 passed" in run.stdout


def test_deploy_installs_and_reloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake_rcon: FakeRcon
) -> None:
    game = _game(tmp_path)
    root = _project(tmp_path / "proj", f'[tool.amxpy.server]\ngame = "{game.as_posix()}"\nport = {fake_rcon.port}\n')
    monkeypatch.chdir(root)
    monkeypatch.delenv("AMXPY_RCON_PASSWORD", raising=False)  # пароль — из server.cfg

    assert main(["deploy"]) == 0
    printed = capsys.readouterr().out
    for rel in ("addons/amxpy/plugins/hello.amxpy", "addons/amxpy/plugins/vip.amxpy", "addons/amxmodx/scripting/include/vip.inc"):
        assert (game / rel).is_file(), rel
    assert (game / "addons" / "amxpy" / "plugins.ini").read_text() == "; plugins\nhello\nvip\n"
    assert fake_rcon.commands == ["amxpy list", "amxpy reload hello", "amxpy load vip"]
    assert re.search(r"vip\s+✓\s+amxpy load", printed), printed

    fake_rcon.commands.clear()
    assert main(["deploy", "src/vip/perks.py"]) == 0  # любой файл плагина — как задача «установить этот плагин»
    assert fake_rcon.commands == ["amxpy list", "amxpy reload vip"]

    capsys.readouterr()
    assert main(["rcon", "amxpy", "list"]) == 0
    assert "vip" in capsys.readouterr().out


def test_deploy_reports_rcon_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake_rcon: FakeRcon
) -> None:
    game = _game(tmp_path, password="wrong")
    root = _project(tmp_path / "proj", f'[tool.amxpy.server]\ngame = "{game.as_posix()}"\nport = {fake_rcon.port}\n')
    monkeypatch.chdir(root)
    monkeypatch.delenv("AMXPY_RCON_PASSWORD", raising=False)
    assert main(["deploy", "hello"]) == 1
    assert (game / "addons" / "amxpy" / "plugins" / "hello.amxpy").is_file()  # файлы уже на месте
    assert "неверный rcon_password" in capsys.readouterr().err


def test_deploy_needs_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(_project(tmp_path / "proj"))
    assert main(["deploy"]) == 2
    assert "[tool.amxpy.server]" in capsys.readouterr().err


def test_init_writes_no_machine_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from amxpy import scaffold

    monkeypatch.setattr(scaffold, "_hidden_from_pylance", lambda target: "/somewhere/amxpy")  # editable с import hook
    proj = tmp_path / "proj"
    assert main(["init", str(proj)]) == 0
    text = (proj / ".vscode" / "settings.json").read_text(encoding="utf-8")
    assert "/somewhere" not in text and sys.prefix not in text  # настройки проекта одинаковы на любой машине
    assert "python.analysis.extraPaths" not in json.loads(text)
    out = capsys.readouterr().out
    assert "editable_mode=compat" in out and "/somewhere/amxpy[dev]" in out
    assert "Python: Select Interpreter" in out  # окружение вне проекта — выбирается в VS Code


def test_init_uses_project_venv_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    proj = tmp_path / "proj"
    monkeypatch.setattr(sys, "executable", str(proj / ".venv" / "bin" / "python3.14"))
    assert main(["init", str(proj)]) == 0
    settings = json.loads((proj / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.defaultInterpreterPath"] == "${workspaceFolder}/.venv/bin/python3.14"


def test_init_drops_stale_amxpy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from amxpy import scaffold

    monkeypatch.setattr(scaffold, "_hidden_from_pylance", lambda target: None)  # amxpy уже виден Pylance
    source = str(Path(scaffold.__file__).resolve().parent.parent)
    proj = tmp_path / "proj"
    vscode = proj / ".vscode"
    vscode.mkdir(parents=True)
    (vscode / "settings.json").write_text(json.dumps({"python.analysis.extraPaths": [source, "/my/libs"]}))
    assert main(["init", str(proj)]) == 0
    settings = json.loads((vscode / "settings.json").read_text(encoding="utf-8"))
    assert settings["python.analysis.extraPaths"] == ["/my/libs"]  # чужой путь не трогаем

    (vscode / "settings.json").write_text(json.dumps({"python.analysis.extraPaths": [source]}))
    assert main(["init", str(proj)]) == 0
    assert "python.analysis.extraPaths" not in json.loads((vscode / "settings.json").read_text(encoding="utf-8"))

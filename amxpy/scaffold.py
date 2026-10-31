"""``amxpy init``: проект плагинов с настройками VS Code.

Существующее не перезаписывается: в settings.json, tasks.json и extensions.json
дописывается только то, чего в них нет, а пример плагина и тест к нему
появляются, только если в папке плагинов ещё пусто.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .compiler import WARNING_CODES
from .events import CATALOG
from .project import load_project

_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

_GITIGNORE = "__pycache__/\n.venv/\n.pytest_cache/\ndist/\n"

_PYTEST = """
[tool.pytest.ini_options]
testpaths = ["tests"]
"""

_PLUGIN = '''\
"""{title}: приветствие и команда /hp."""

from amxpy import Config, Player, Plugin, cvar, events, sleep

plugin = Plugin("{title}", version="0.1.0")


class Settings(Config, prefix="{name}_"):
    delay: float = cvar(3.0, "Задержка приветствия, сек", min=0)


cfg = plugin.include(Settings())


@plugin.on(events.PutInServer)
async def greet(e: events.PutInServer) -> None:
    player = e.player  # событие живёт до первого await — игрока берём заранее
    await sleep(cfg.delay)
    player.print(f"!gПривет, !t{{player.name}}!y! Набери !g/hp")


@plugin.command("/hp", help="Показать здоровье")
def hp(player: Player) -> None:
    player.print(f"HP: {{player.health}}, броня: {{player.armor}}")
'''

_TEST = '''\
from pathlib import Path

from amxpy.testing import FakeServer

PLUGIN = Path(__file__).resolve().parents[1] / "{plugin}"


def test_greets_after_delay(server: FakeServer) -> None:
    server.load(PLUGIN)
    bob = server.join("Bob")
    server.run(3.5)
    assert "Привет, Bob" in bob.last_chat


def test_hp(server: FakeServer) -> None:
    server.load(PLUGIN)
    bob = server.join("Bob", health=42)
    bob.say("/hp")
    assert bob.last_chat == "HP: 42, броня: 0"
'''


def _tool_section(game: str | None, docker: str | None, host: str, port: int) -> str:
    off = "" if game else "# "  # без папки сервера секция остаётся примером
    lines = [
        "[tool.amxpy]",
        'plugins = "plugins"   # исходники: файлы *.py и папки с __init__.py',
        'out = "dist"          # куда собирать пакеты .amxpy',
        "",
        "# Сервер для amxpy deploy и amxpy rcon: game — папка мода на сервере, docker —",
        "# контейнер, если сервер в Docker. Пароль RCON: переменная AMXPY_RCON_PASSWORD,",
        "# иначе rcon_password из server.cfg сервера.",
        f"{off}[tool.amxpy.server]",
        f"{off}game = {json.dumps(game or '/home/hlds/cstrike')}",
        f"{'' if docker else '# '}docker = {json.dumps(docker or 'hlds')}",
        f"{off}host = {json.dumps(host)}",
        f"{off}port = {port}",
    ]
    return "\n".join(lines) + "\n"


def _interpreter(target: Path) -> str | None:
    """Интерпретатор amxpy init (в нём уже есть amxpy) — если он внутри проекта, иначе None.

    Путь вне проекта свой на каждой машине: его выбирают в VS Code (Python: Select Interpreter),
    и выбор хранится у VS Code, а не в настройках проекта.
    """
    try:
        return "${workspaceFolder}/" + Path(sys.executable).relative_to(target).as_posix()
    except ValueError:
        return None


def _source_root() -> Path:
    """Корень исходников amxpy (папка с pyproject.toml при установке через ``pip install -e``)."""
    return Path(__file__).resolve().parent.parent


def _hidden_from_pylance(target: Path) -> str | None:
    """Папка исходников amxpy, если Pylance её не видит, иначе None.

    ``pip install -e`` в режиме по умолчанию подключает пакет import hook'ом — Python его находит,
    а Pylance нет. С ``--config-settings editable_mode=compat`` (или обычной установкой) путь лежит
    в sys.path. Сам путь в настройки проекта не пишется: он свой на каждой машине.
    """
    package = Path(__file__).resolve().parent
    root = _source_root()
    if {"site-packages", "dist-packages"} & set(package.parts) or root == target:
        return None
    on_path = {Path(p).resolve() for p in sys.path if p}
    return None if root in on_path else str(root)


def _settings(target: Path) -> dict[str, Any]:
    severity = {"E": "Error", "F": "Error", "I": "Information", "W": "Warning", "AMX": "Error"}
    severity.update({code: "Warning" for code in sorted(WARNING_CODES)})
    settings: dict[str, Any] = {
        "python.analysis.typeCheckingMode": "standard",
        "python.analysis.autoImportCompletions": True,  # cycle → from itertools import cycle
        "python.testing.pytestEnabled": True,
        "python.testing.unittestEnabled": False,
        "flake8.importStrategy": "fromEnvironment",  # flake8 из окружения — с плагином amxpy
        # amxpyc + то, чего Pylance не показывает ошибкой: неиспользуемый импорт, переопределение, лишняя переменная
        "flake8.args": ["--select=AMX,F401,F811,F841"],
        "flake8.severity": severity,
    }
    interpreter = _interpreter(target)
    if interpreter:
        settings["python.defaultInterpreterPath"] = interpreter
    return settings


def _matcher(severity: str, word: str) -> dict[str, Any]:
    """Problem matcher для вывода ``amxpy build``: ``файл:строка:столбец: ошибка AMX101: текст``."""
    return {
        "owner": "amxpy",
        "source": "amxpyc",
        "fileLocation": ["autoDetect", "${workspaceFolder}"],
        "severity": severity,
        "pattern": {
            "regexp": rf"^\s*(.+?):(\d+):(\d+): {word} (AMX\d+): (.*)$",
            "file": 1,
            "line": 2,
            "column": 3,
            "code": 4,
            "message": 5,
        },
    }


def _tasks() -> dict[str, Any]:
    matchers = [_matcher("error", "ошибка"), _matcher("warning", "предупреждение")]

    def task(label: str, *args: str, matched: bool = False, **extra: Any) -> dict[str, Any]:
        return {
            "label": label,
            "type": "process",
            "command": "${command:python.interpreterPath}",
            "args": ["-m", *args],
            "problemMatcher": matchers if matched else [],
            **extra,
        }

    return {
        "version": "2.0.0",
        "tasks": [
            task("amxpy: собрать", "amxpy", "build", matched=True, group={"kind": "build", "isDefault": True}),
            task("amxpy: установить этот плагин на сервер", "amxpy", "deploy", "${file}", matched=True),
            task("amxpy: установить все плагины на сервер", "amxpy", "deploy", matched=True),
            task("amxpy: перезагрузить плагин на сервере", "amxpy", "rcon", "amxpy reload ${input:amxpyPlugin}"),
            task("amxpy: плагины на сервере", "amxpy", "rcon", "amxpy list"),
            task("amxpy: тесты", "pytest", group="test"),
        ],
        "inputs": [{"id": "amxpyPlugin", "type": "promptString", "description": "Имя плагина (как в amxpy list)"}],
    }


def _snippet(prefix: str, description: str, *body: str) -> dict[str, Any]:
    return {"scope": "python", "prefix": prefix, "description": description, "body": list(body)}


def _snippets() -> dict[str, Any]:
    events = ",".join(CATALOG)
    return {
        "amxpy: плагин": _snippet(
            "amxplugin",
            "Новый плагин amxpy",
            "from amxpy import Player, Plugin, events",
            "",
            'plugin = Plugin("${1:Название}", version="0.1.0")',
            "",
            "",
            "@plugin.on(events.${2|" + events + "|})",
            "def ${3:handler}(e: events.$2) -> None:",
            "    $0",
        ),
        "amxpy: обработчик события": _snippet(
            "amxon",
            "@plugin.on(events.…)",
            "@${1:plugin}.on(events.${2|" + events + "|})",
            "${3|def,async def|} ${4:handler}(e: events.$2) -> None:",
            "    $0",
        ),
        "amxpy: команда": _snippet(
            "amxcmd",
            "Команда игрока в чате или консоли",
            '@${1:plugin}.command("/${2:name}", help="${3:Описание}")',
            "def ${4:handler}(player: Player) -> None:",
            "    $0",
        ),
        "amxpy: команда админа": _snippet(
            "amxadmin",
            "Консольная команда с доступом и целью",
            '@${1:plugin}.command("${2:amx_name}", access=Access.${3|KICK,BAN,SLAY,MAP,CVAR,CFG,CHAT,VOTE,RCON,MENU|},'
            ' help="${4:Описание}")',
            "def ${5:handler}(admin: Player, target: Player${6:, amount: int = 1}) -> None:",
            "    $0",
        ),
        "amxpy: натив": _snippet(
            "amxnative",
            "Натив для Pawn-плагинов (попадёт в .inc)",
            "@${1:plugin}.native",
            "def ${2:plugin_name}(player: Player) -> ${3|int,bool,float,str,None|}:",
            '    """${4:Описание для .inc}"""',
            "    $0",
        ),
        "amxpy: форвард": _snippet(
            "amxforward",
            "Форвард для Pawn и Python",
            '${1:granted} = ${2:plugin}.forward("${3:plugin_granted}", player=Player${4:, value=int})',
        ),
        "amxpy: cvar'ы": _snippet(
            "amxcfg",
            "Группа cvar'ов плагина",
            'class ${1:Settings}(Config, prefix="${2:plugin_}"):',
            '    ${3:value}: ${4|int,float,bool,str|} = cvar(${5:0}, "${6:Описание}")',
            "",
            "",
            "${7:cfg} = ${8:plugin}.include($1())",
        ),
        "amxpy: меню": _snippet(
            "amxmenu",
            "Меню с пунктом",
            '${1:menu} = Menu("${2:Заголовок}")',
            "",
            "",
            '@$1.item("${3:Пункт}")',
            "def ${4:on_item}(player: Player) -> None:",
            "    $0",
        ),
        "amxpy: периодическая задача": _snippet(
            "amxevery",
            "Задача раз в N секунд",
            "@${1:plugin}.every(${2:1.0})",
            "def ${3:tick}() -> None:",
            "    $0",
        ),
        "amxpy: данные игроков": _snippet(
            "amxstate",
            "PlayerState: данные по игрокам",
            "${1:data}: PlayerState[${2:int}] = PlayerState(${3:int}${4:, keep=True})",
        ),
        "amxpy: тест": _snippet(
            "amxtest",
            "Тест на FakeServer",
            "def test_${1:name}(server: FakeServer) -> None:",
            '    server.load("${2:plugins/plugin.py}")',
            '    ${3:player} = server.join("${4:Player}")',
            "    $0",
        ),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def _merge_json(path: Path, fresh: dict[str, Any], merge: Callable[[dict[str, Any]], list[str]]) -> str:
    """Создать файл или дописать в него недостающее; пометка для отчёта."""
    if not path.exists():
        _write_json(path, fresh)
        return "+"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "! не JSON (комментарии?) — не тронут"
    changes = merge(data)
    if not changes:
        return "="
    _write_json(path, data)
    added = [c for c in changes if not c.startswith("убран")]
    notes = (["дописано: " + ", ".join(added)] if added else []) + [c for c in changes if c.startswith("убран")]
    return "~ " + "; ".join(notes)


def _merge_settings(fresh: dict[str, Any], stale: str | None = None) -> Callable[[dict[str, Any]], list[str]]:
    """Дописать недостающие ключи; ``stale`` — путь к amxpy, который прежний init клал в extraPaths."""

    def merge(data: dict[str, Any]) -> list[str]:
        added = [key for key in fresh if key not in data]
        data.update({key: fresh[key] for key in added})
        paths = data.get("python.analysis.extraPaths")
        if stale and isinstance(paths, list) and stale in paths:
            paths.remove(stale)
            if not paths:
                del data["python.analysis.extraPaths"]
            added.append("убран путь к amxpy из extraPaths")
        return added

    return merge


def _merge_tasks(fresh: dict[str, Any]) -> Callable[[dict[str, Any]], list[str]]:
    def merge(data: dict[str, Any]) -> list[str]:
        data.setdefault("version", "2.0.0")
        tasks = data.setdefault("tasks", [])
        labels = {t.get("label") for t in tasks}
        added = [t for t in fresh["tasks"] if t["label"] not in labels]
        tasks.extend(added)
        inputs = data.setdefault("inputs", [])
        ids = {i.get("id") for i in inputs}
        inputs.extend(i for i in fresh["inputs"] if i["id"] not in ids)
        return [t["label"] for t in added]

    return merge


def _merge_extensions(fresh: dict[str, Any]) -> Callable[[dict[str, Any]], list[str]]:
    def merge(data: dict[str, Any]) -> list[str]:
        recommended = data.setdefault("recommendations", [])
        added = [ext for ext in fresh["recommendations"] if ext not in recommended]
        recommended.extend(added)
        return added

    return merge


def init_project(
    target: Path,
    *,
    name: str = "hello",
    game: str | None = None,
    docker: str | None = None,
    host: str = "127.0.0.1",
    port: int = 27015,
) -> int:
    """Создать или дополнить проект плагинов в ``target``."""
    if not _NAME_RE.match(name):
        print(f"имя плагина {name!r}: латиница в нижнем регистре, цифры и _", file=sys.stderr)
        return 2
    target = target.resolve()
    target.mkdir(parents=True, exist_ok=True)
    report: list[tuple[str, str]] = []

    pyproject = target / "pyproject.toml"
    tool = _tool_section(game, docker, host, port)
    if not pyproject.exists():
        pyproject.write_text(tool + _PYTEST, encoding="utf-8")
        report.append(("pyproject.toml", "+"))
    else:
        text = pyproject.read_text(encoding="utf-8")
        try:
            has_tool = "amxpy" in tomllib.loads(text).get("tool", {})
        except tomllib.TOMLDecodeError as exc:
            print(f"{pyproject}: {exc}", file=sys.stderr)
            return 1
        if has_tool:
            report.append(("pyproject.toml", "="))
        else:
            pyproject.write_text(text.rstrip("\n") + "\n\n" + tool, encoding="utf-8")
            report.append(("pyproject.toml", "~ дописано: [tool.amxpy]"))

    plugins = load_project(target).plugins
    if not (plugins.is_dir() and any(p.suffix == ".py" or p.is_dir() for p in plugins.iterdir())):
        sample = plugins / f"{name}.py"
        sample.parent.mkdir(parents=True, exist_ok=True)
        sample.write_text(_PLUGIN.format(name=name, title=name.replace("_", " ").capitalize()), encoding="utf-8")
        report.append((sample.relative_to(target).as_posix(), "+"))
        test = target / "tests" / f"test_{name}.py"
        if not test.exists():
            test.parent.mkdir(parents=True, exist_ok=True)
            test.write_text(_TEST.format(plugin=sample.relative_to(target).as_posix()), encoding="utf-8")
            report.append((test.relative_to(target).as_posix(), "+"))

    gitignore = target / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(_GITIGNORE, encoding="utf-8")
        report.append((".gitignore", "+"))

    vscode = target / ".vscode"
    settings = _settings(target)
    tasks = _tasks()
    extensions = {"recommendations": ["ms-python.python", "ms-python.vscode-pylance", "ms-python.flake8", "amxpy.amxpy"]}
    hidden = _hidden_from_pylance(target)
    stale = None if hidden else str(_source_root())  # amxpy виден Pylance — старый путь больше не нужен
    report.append((".vscode/settings.json", _merge_json(vscode / "settings.json", settings, _merge_settings(settings, stale))))
    report.append((".vscode/tasks.json", _merge_json(vscode / "tasks.json", tasks, _merge_tasks(tasks))))
    report.append(
        (".vscode/extensions.json", _merge_json(vscode / "extensions.json", extensions, _merge_extensions(extensions)))
    )
    snippets = vscode / "amxpy.code-snippets"
    if snippets.exists():
        report.append((".vscode/amxpy.code-snippets", "="))
    else:
        _write_json(snippets, _snippets())
        report.append((".vscode/amxpy.code-snippets", "+"))

    print(f"amxpy init → {target}")
    for rel, mark in report:
        sign, _, note = mark.partition(" ")
        print(f"  {sign} {rel}" + (f"  ({note})" if note else ""))
    print("\nДальше:")
    if importlib.util.find_spec("flake8") is None:
        print(f"  • ошибки amxpyc в редакторе — нужен flake8: {sys.executable} -m pip install flake8")
    print("  • откройте папку в VS Code и поставьте рекомендованные расширения: Python, Pylance, Flake8")
    if _interpreter(target) is None:
        print(f"  • интерпретатор — Ctrl+Shift+P → Python: Select Interpreter → {sys.executable}")
    if hidden:
        print("  • Pylance не видит amxpy, установленный через pip install -e: переустановите его так")
        print(f"      {sys.executable} -m pip install -e '{hidden}[dev]' --config-settings editable_mode=compat")
    print("  • Ctrl+Shift+B — сборка; «Задачи: запустить задачу» — установка на сервер и перезагрузка")
    if load_project(target).server is None:
        print("  • сервер для установки — [tool.amxpy.server] в pyproject.toml")
    return 0

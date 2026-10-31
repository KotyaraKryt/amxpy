"""Командная строка: компилятор amxpyc, установка плагинов на сервер, RCON и ``amxpy init``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .compiler import VERSION, CompileResult, build, plugin_root
from .package import BYTECODE_TAG
from .project import Project, ProjectError, Server, load_project


def _rel(path: Path) -> Path:
    """Путь от текущей папки, если он внутри неё: короче в выводе, и редактор открывает его по клику."""
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def _discover(root: Path) -> list[Path]:
    """Плагины в папке: файлы *.py и папки с __init__.py."""
    if not root.is_dir():
        return []
    return sorted(
        p
        for p in root.iterdir()
        if (p.is_file() and p.suffix == ".py" and not p.name.startswith("_"))
        or (p.is_dir() and (p / "__init__.py").is_file())
    )


def _summary(result: CompileResult) -> str:
    assert result.package is not None
    manifest = result.package.manifest
    parts = [f"модулей {len(result.package.modules)}"]
    for key, label in (
        ("events", "событий"),
        ("commands", "команд"),
        ("natives", "нативов"),
        ("forwards", "форвардов"),
        ("cvars", "cvar"),
    ):
        if manifest.get(key):
            parts.append(f"{label} {len(manifest[key])}")
    return " · ".join(parts)


def _build(sources: list[Path], out: Path, *, release: bool) -> list[CompileResult]:
    print(f"amxpyc {VERSION} · {BYTECODE_TAG} → {out}/")
    results = build(sources, out, release=release)
    for result in results:
        mark = "✓" if result.ok else "✗"
        print(f"  {result.name:<16} {mark}  {_summary(result) if result.ok else ''}".rstrip())
        for diagnostic in result.diagnostics:
            print(f"      {diagnostic.format()}")
    return results


def cmd_build(args: argparse.Namespace) -> int:
    project = load_project()
    sources = args.sources or _discover(_rel(project.plugins))
    if not sources:
        print(f"нечего собирать: укажите файлы или папки плагинов (или создайте {_rel(project.plugins)}/)", file=sys.stderr)
        return 2
    results = _build(sources, args.out or _rel(project.out), release=args.release)
    return 1 if any(not r.ok or (args.werror and r.warnings) for r in results) else 0


def _plugin_source(project: Project, arg: str) -> Path:
    """Плагин по пути (сам плагин или любой его файл) или по имени из папки плагинов проекта."""
    path = Path(arg)
    if not path.exists():
        path = next((p for p in (project.plugins / f"{arg}.py", project.plugins / arg) if p.exists()), path)
    if not path.exists():
        raise ProjectError(f"плагин {arg!r} не найден ни по пути, ни в {_rel(project.plugins)}/")
    return _rel(plugin_root(path))


def _loaded(listing: str) -> set[str]:
    """Имена плагинов из ответа ``amxpy list``."""
    return {line.split()[0] for line in listing.splitlines() if line.startswith("  ") and line.strip()}


def _register(server: Server, names: list[str]) -> None:
    """Дописать новые плагины в plugins.ini, чтобы они загружались и после рестарта сервера."""
    ini = server.read("addons/amxpy/plugins.ini") or ""
    listed = {line.split(";", 1)[0].split("//", 1)[0].strip().removesuffix(".amxpy") for line in ini.splitlines()}
    missing = [name for name in names if name not in listed]
    if missing:
        head = ini if not ini or ini.endswith("\n") else ini + "\n"
        server.write("addons/amxpy/plugins.ini", head + "".join(f"{name}\n" for name in missing))
        print(f"  plugins.ini: + {', '.join(missing)}")


def cmd_deploy(args: argparse.Namespace) -> int:
    from .rcon import RconError, rcon

    project = load_project()
    server = project.server
    if server is None:
        print("сервер не настроен: добавьте [tool.amxpy.server] в pyproject.toml (см. amxpy init)", file=sys.stderr)
        return 2
    sources = [_plugin_source(project, arg) for arg in args.plugins] or _discover(_rel(project.plugins))
    if not sources:
        print(f"нечего устанавливать: в {_rel(project.plugins)}/ нет плагинов", file=sys.stderr)
        return 2
    out = _rel(project.out)
    results = _build(sources, out, release=args.release)
    built = [r for r in results if r.ok]
    failed = len(results) - len(built)
    if not built:
        return 1
    print(f"установка → {server}")
    try:
        for r in built:
            server.put(out / f"{r.name}.amxpy", f"addons/amxpy/plugins/{r.name}.amxpy")
            if r.include is not None:
                server.put(out / "include" / f"{r.name}.inc", f"addons/amxmodx/scripting/include/{r.name}.inc")
        _register(server, [r.name for r in built])
        password = server.rcon_password()
        loaded = _loaded(rcon(server.host, server.port, password, "amxpy list"))
        for r in built:
            verb = "reload" if r.name in loaded else "load"
            reply = rcon(server.host, server.port, password, f"amxpy {verb} {r.name}")
            ok = f"{verb} {r.name}: ok" in reply
            print(f"  {r.name:<16} {'✓' if ok else '✗'}  amxpy {verb}")
            if not ok:
                failed += 1
                for line in reply.strip().splitlines():
                    print(f"      {line}")
    except (ProjectError, RconError, OSError) as exc:
        print(f"сервер: {exc}", file=sys.stderr)
        return 1
    return 1 if failed else 0


def cmd_rcon(args: argparse.Namespace) -> int:
    from .rcon import RconError, rcon

    server = load_project().server
    host = args.host or (server.host if server else "127.0.0.1")
    port = args.port or (server.port if server else 27015)
    try:
        password = args.password or os.environ.get("AMXPY_RCON_PASSWORD", "")
        if not password and server is not None and args.host is None and args.port is None:
            password = server.rcon_password()  # rcon_password из server.cfg настроенного сервера
        print(rcon(host, port, password, " ".join(args.command)), end="")
    except (ProjectError, RconError, OSError) as exc:
        print(f"rcon: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    from .scaffold import init_project

    return init_project(args.dir, name=args.name, game=args.game, docker=args.docker, host=args.host, port=args.port)


def build_parser() -> argparse.ArgumentParser:
    """Парсер командной строки ``amxpy`` (по нему же строится справочник CLI в документации)."""
    parser = argparse.ArgumentParser(prog="amxpy", description="amxpy — плагины AMX Mod X на Python")
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="собрать плагины в пакеты .amxpy")
    b.add_argument("sources", nargs="*", type=Path, help="файлы .py и папки плагинов (по умолчанию — все из проекта)")
    b.add_argument("-o", "--out", type=Path, help="куда писать (по умолчанию — out из [tool.amxpy] или dist/)")
    b.add_argument("--release", action="store_true", help="без исходников в пакете, optimize=2")
    b.add_argument("--werror", action="store_true", help="предупреждения считать ошибками")
    b.set_defaults(func=cmd_build)

    d = sub.add_parser("deploy", help="собрать, установить на сервер из [tool.amxpy.server] и перезагрузить")
    d.add_argument("plugins", nargs="*", help="пути или имена плагинов (по умолчанию — все); подойдёт любой файл плагина")
    d.add_argument("--release", action="store_true", help="без исходников в пакете, optimize=2")
    d.set_defaults(func=cmd_deploy)

    r = sub.add_parser("rcon", help="команда серверу по RCON")
    r.add_argument("command", nargs="+", help="например: amxpy list")
    r.add_argument("--host", help="по умолчанию — из [tool.amxpy.server] или 127.0.0.1")
    r.add_argument("--port", type=int, help="по умолчанию — из [tool.amxpy.server] или 27015")
    r.add_argument("--password", help="rcon_password (иначе AMXPY_RCON_PASSWORD или server.cfg настроенного сервера)")
    r.set_defaults(func=cmd_rcon)

    i = sub.add_parser("init", help="проект плагинов с настройками VS Code")
    i.add_argument("dir", nargs="?", type=Path, default=Path("."), help="папка проекта (по умолчанию — текущая)")
    i.add_argument("--name", default="hello", help="имя примера плагина")
    i.add_argument("--game", help="папка мода на сервере для [tool.amxpy.server]")
    i.add_argument("--docker", help="контейнер Docker с сервером")
    i.add_argument("--host", default="127.0.0.1", help="адрес сервера для RCON")
    i.add_argument("--port", type=int, default=27015, help="порт сервера для RCON")
    i.set_defaults(func=cmd_init)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except ProjectError as exc:
        print(f"amxpy: {exc}", file=sys.stderr)
        return 2

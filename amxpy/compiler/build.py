"""amxpyc: исходники плагина → пакет .amxpy (+ .inc для Pawn, .cfg с cvar'ами)."""

from __future__ import annotations

import ast
import functools
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..config import render_cfg
from ..package import API_VERSION, BYTECODE_TAG, FORMAT, MAGIC, ModuleEntry, PluginPackage, make_pyc, write_package
from .analyzer import Analyzer, Declarations, SourceModule
from .diagnostics import Diagnostic
from .pawn import render_include

VERSION = "0.1.0"
_PLUGIN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SKIP_DIRS = {"__pycache__", "tests", ".git"}
_IMPORTS_AMXPY = re.compile(r"^\s*(?:from|import)\s+amxpy\b", re.MULTILINE)


@dataclass
class CompileResult:
    name: str
    diagnostics: list[Diagnostic]
    package: PluginPackage | None = None
    include: str | None = None
    cfg: str | None = None

    @property
    def ok(self) -> bool:
        return self.package is not None

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]

    def require(self) -> PluginPackage:
        """Пакет или :class:`CompileError` со всеми ошибками."""
        if self.package is None:
            raise CompileError(self)
        return self.package


class CompileError(Exception):
    def __init__(self, result: CompileResult) -> None:
        self.result = result
        lines = [d.format() for d in result.errors] or ["сборка не удалась"]
        super().__init__(f"{result.name}: ошибки компиляции:\n" + "\n".join(lines))


def plugin_root(file: str | Path) -> Path:
    """Плагин, к которому относится файл: верхняя папка пакета с ``__init__.py`` или сам файл."""
    root = Path(file).resolve()
    while (root.parent / "__init__.py").is_file():
        root = root.parent
    return root


def _sources(path: Path, name: str) -> tuple[list[tuple[Path, str, str, bool]], list[Path]]:
    """[(файл, имя модуля, путь внутри пакета, пакет?)] и файлы данных."""
    if path.is_file():
        return [(path, "", path.name, True)], []
    files = sorted(
        p for p in path.rglob("*") if p.is_file() and not (_SKIP_DIRS & set(p.relative_to(path).parts[:-1]))
    )
    modules = []
    for file in (p for p in files if p.suffix == ".py"):
        rel = file.relative_to(path)
        parts = list(rel.with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        modules.append((file, ".".join(parts), f"{name}/{rel.as_posix()}", is_package))
    return modules, [p for p in files if p.suffix not in (".py", ".pyc")]


def _syntax_error(path: str, exc: SyntaxError) -> Diagnostic:
    return Diagnostic("AMX001", "error", path, exc.lineno or 1, exc.offset or 1, f"синтаксическая ошибка: {exc.msg}")


@dataclass
class _Analysis:
    result: CompileResult
    modules: list[SourceModule] = field(default_factory=list)
    data_files: list[Path] = field(default_factory=list)
    decl: Declarations | None = None


def _analyze(path: Path, overrides: Mapping[Path, str]) -> _Analysis:
    """Разобрать и проверить плагин; ``overrides`` — тексты файлов вместо диска (из редактора)."""
    name = path.stem if path.suffix == ".py" else path.name
    analysis = _Analysis(CompileResult(name, []))
    diagnostics = analysis.result.diagnostics
    if path.is_dir():
        if not (path / "__init__.py").is_file():
            diagnostics.append(Diagnostic("AMX005", "error", str(path), 1, 1, "в папке плагина нет __init__.py"))
            return analysis
    elif not (path.suffix == ".py" and path.is_file()):
        diagnostics.append(Diagnostic("AMX005", "error", str(path), 1, 1, "ожидается файл .py или папка с __init__.py"))
        return analysis

    files, analysis.data_files = _sources(path, name)
    for file, module, display, is_package in files:
        text = overrides.get(file.resolve()) if overrides else None
        if text is None:
            text = file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=display)
        except SyntaxError as exc:
            diagnostics.append(_syntax_error(str(file), exc))
            continue
        analysis.modules.append(SourceModule(module, display, str(file), text, tree, is_package))
    if not analysis.result.errors:
        analyzer = Analyzer(analysis.modules)
        analysis.decl = analyzer.run()
        diagnostics.extend(analyzer.diagnostics)
    return analysis


@functools.lru_cache(maxsize=64)
def _uses_amxpy(root: Path) -> bool:
    """Импортирует ли amxpy хоть один модуль пакета (кэш на процесс flake8)."""
    for file in root.rglob("*.py"):
        try:
            if _IMPORTS_AMXPY.search(file.read_text(encoding="utf-8", errors="replace")):
                return True
        except OSError:
            continue
    return False


def check_file(file: str | Path, text: str | None = None) -> list[Diagnostic]:
    """Диагностики одного файла плагина — для редактора (см. :mod:`.lint`).

    Плагин проверяется целиком (:func:`plugin_root`), а возвращаются диагностики
    только этого файла; ``text`` — его текст, если он не совпадает с диском.
    Код без ``Plugin(...)`` плагином не считается: для него диагностик нет.
    """
    path = Path(file).resolve()
    root = plugin_root(path)
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
    # flake8 с этим плагином проверяет и чужой код: без импорта amxpy анализ не нужен
    if not _IMPORTS_AMXPY.search(text) and (root == path or not _uses_amxpy(root)):
        return []
    analysis = _analyze(root, {path: text})
    diagnostics = analysis.result.diagnostics
    if any(d.code == "AMX002" for d in diagnostics):
        return []
    return [d for d in diagnostics if Path(d.file).resolve() == path]


def compile_plugin(source: str | Path, *, release: bool = False) -> CompileResult:
    """Скомпилировать плагин: файл ``name.py`` или папку ``name/`` с ``__init__.py``."""
    path = Path(source)
    name = path.stem if path.suffix == ".py" else path.name
    if not _PLUGIN_NAME_RE.match(name):
        message = f"имя плагина {name!r} должно быть идентификатором Python"
        return CompileResult(name, [Diagnostic("AMX006", "error", str(path), 1, 1, message)])
    analysis = _analyze(path, {})
    result, decl = analysis.result, analysis.decl
    if decl is None or result.errors:
        return result

    entries: dict[str, ModuleEntry] = {}
    for m in analysis.modules:
        try:
            code = compile(m.source, m.file, "exec", dont_inherit=True, optimize=2 if release else 0)
        except SyntaxError as exc:
            result.diagnostics.append(_syntax_error(m.path, exc))
            continue
        pyc = make_pyc(code, m.source.encode("utf-8"))
        entries[m.name] = ModuleEntry(m.name, m.file, m.is_package, pyc, None if release else m.source)
    if result.errors:
        return result

    title = decl.meta.get("title", name)
    manifest = {
        "format": FORMAT,
        "name": name,
        "title": title,
        "version": decl.meta.get("version", "0.0.0"),
        "author": decl.meta.get("author", ""),
        "description": decl.meta.get("description", ""),
        "url": decl.meta.get("url", ""),
        "runtime": {"bytecode": BYTECODE_TAG, "magic": MAGIC.hex(), "api": API_VERSION},
        "modules": [{"name": e.name, "file": e.file, "package": e.is_package} for e in entries.values()],
        "events": decl.events,
        "commands": decl.commands,
        "server_commands": decl.server_commands,
        "natives": decl.natives,
        "forwards": decl.forwards,
        "cvars": decl.cvars,
        "build": {"compiler": f"amxpyc {VERSION}", "release": release},
    }
    data = {p.relative_to(path).as_posix(): p.read_bytes() for p in analysis.data_files}
    result.package = PluginPackage(manifest, entries, data)
    if decl.natives or decl.forwards:
        result.include = render_include(name, title, decl.natives, decl.forwards)
    if decl.cvars:
        result.cfg = render_cfg(title, decl.cvars)
    return result


def build(sources: Iterable[str | Path], out_dir: str | Path, *, release: bool = False) -> list[CompileResult]:
    """Собрать плагины в ``out_dir``: ``*.amxpy``, ``include/*.inc``, ``configs/*.cfg``."""
    out = Path(out_dir)
    results = []
    for source in sources:
        result = compile_plugin(source, release=release)
        if result.package is not None:
            write_package(result.package, out / f"{result.name}.amxpy")
            if result.include is not None:
                (out / "include").mkdir(parents=True, exist_ok=True)
                (out / "include" / f"{result.name}.inc").write_text(result.include, encoding="utf-8")
            if result.cfg is not None:
                (out / "configs").mkdir(parents=True, exist_ok=True)
                (out / "configs" / f"{result.name}.cfg").write_text(result.cfg, encoding="utf-8")
        results.append(result)
    return results

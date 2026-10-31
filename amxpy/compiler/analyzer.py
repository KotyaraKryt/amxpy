"""Статический анализ плагина: декларации для манифеста и диагностики.

Компилятор не выполняет код плагина — всё берётся из AST. Поэтому аргументы
деклараций (события, имена команд, нативов, форвардов, cvar'ов) должны быть
литералами: только так C++-модуль узнаёт о них до запуска Python-кода.

Коды диагностик:
    AMX001 синтаксис            AMX002–AMX006 плагин и его метаданные
    AMX100–AMX108 события       AMX201–AMX206 нативы и форварды
    AMX301 побочный эффект при импорте
    AMX401–AMX406 команды и cvar'ы
    AMX103 блокирующий вызов в обработчике
"""

from __future__ import annotations

import ast
import difflib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from ..config import format_value
from ..events import CATALOG
from ..plugin import CHAT_COMMAND_RE, CONSOLE_COMMAND_RE, NAME_RE
from .diagnostics import WARNING_CODES, Diagnostic

_CANON = {
    "amxpy.plugin.Plugin": "amxpy.Plugin",
    "amxpy.plugin.Router": "amxpy.Router",
    "amxpy.config.Config": "amxpy.Config",
    "amxpy.config.cvar": "amxpy.cvar",
    "amxpy.player.Player": "amxpy.Player",
}
_PAWN_CODES = {"int": "i", "float": "f", "bool": "b", "str": "s", "amxpy.Player": "p"}
_CVAR_TYPES: dict[str, type] = {"int": int, "float": float, "bool": bool, "str": str}
_CVAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_ROUTER_METHODS = {"on", "command", "server_command", "native", "every", "on_forward"}

_BLOCKING: dict[str, str] = {
    "time.sleep": "await amxpy.sleep(...)",
    "urllib.request.urlopen": "aiohttp, httpx или router.offload(...)",
    "socket.create_connection": "asyncio.open_connection(...)",
    "sqlite3.connect": "amxpy.storage.Table или router.offload(...)",
    "subprocess.run": "asyncio.create_subprocess_exec(...)",
    "subprocess.call": "asyncio.create_subprocess_exec(...)",
    "subprocess.check_call": "asyncio.create_subprocess_exec(...)",
    "subprocess.check_output": "asyncio.create_subprocess_exec(...)",
    "input": "ввода с консоли на игровом сервере нет",
}
for _verb in ("get", "post", "put", "patch", "delete", "head", "request"):
    _BLOCKING[f"requests.{_verb}"] = "aiohttp или httpx (async)"

_IMPORT_TIME = set(_BLOCKING) | {
    "open",
    "socket.socket",
    "asyncio.run",
    "asyncio.create_task",
    "asyncio.ensure_future",
    "threading.Thread",
    "subprocess.Popen",
    "aiohttp.ClientSession",
}

_MISSING = object()


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        return _MISSING
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return _MISSING


def _suggest(word: str, options: Iterable[str]) -> str:
    match = difflib.get_close_matches(word, list(options), n=1)
    return f" — может быть, {match[0]}?" if match else ""


def _scope(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """Узлы одной области видимости, без вложенных функций и классов."""
    stack = list(nodes)
    while stack:
        node = stack.pop()
        yield node
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                stack.append(child)


@dataclass
class SourceModule:
    name: str  # относительное имя модуля ("" — корень плагина)
    file: str  # путь внутри пакета: имя файла кода и трейсбеков на сервере
    path: str  # путь на диске — для диагностик
    source: str
    tree: ast.Module
    is_package: bool


@dataclass
class Declarations:
    meta: dict[str, str] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    commands: list[dict[str, Any]] = field(default_factory=list)
    server_commands: list[dict[str, Any]] = field(default_factory=list)
    natives: list[dict[str, Any]] = field(default_factory=list)
    forwards: list[dict[str, Any]] = field(default_factory=list)
    cvars: list[dict[str, Any]] = field(default_factory=list)


class Analyzer:
    def __init__(self, modules: list[SourceModule]) -> None:
        self.modules = modules
        self.decl = Declarations()
        self.diagnostics: list[Diagnostic] = []
        self.plugins: list[tuple[SourceModule, ast.Call]] = []
        self.command_names: set[str] = set()
        self.native_names: set[str] = set()
        self.forward_names: set[str] = set()
        self.cvar_names: set[str] = set()

    def run(self) -> Declarations:
        for module in self.modules:
            _ModuleVisitor(self, module).run()
        self._check_plugin()
        return self.decl

    def report(self, module: SourceModule, node: ast.AST, code: str, message: str) -> None:
        self.diagnostics.append(
            Diagnostic(
                code,
                "warning" if code in WARNING_CODES else "error",
                module.path,
                getattr(node, "lineno", 1),
                getattr(node, "col_offset", 0) + 1,
                message,
            )
        )

    def _check_plugin(self) -> None:
        if not self.plugins:
            root = next((m for m in self.modules if m.name == ""), self.modules[0])
            self.report(root, root.tree, "AMX002", 'в плагине нет Plugin(...): создайте его, например plugin = Plugin("Имя")')
            return
        for module, call in self.plugins[1:]:
            self.report(module, call, "AMX004", "Plugin(...) создаётся больше одного раза")
        module, call = self.plugins[0]
        meta: dict[str, str] = {}
        fields = [("title", call.args[0])] if call.args else []
        fields += [("title" if kw.arg == "name" else str(kw.arg), kw.value) for kw in call.keywords]
        for key, node in fields:
            if key not in ("title", "version", "author", "description", "url"):
                continue
            value = _literal(node)
            if isinstance(value, str):
                meta[key] = value
            else:
                self.report(module, node, "AMX003", f"{'название' if key == 'title' else key} должно быть строкой-литералом")
        if "title" not in meta and not any(d.code == "AMX003" for d in self.diagnostics):
            self.report(module, call, "AMX003", 'укажите название: Plugin("Имя", version="1.0.0")')
        self.decl.meta = meta


class _ModuleVisitor:
    def __init__(self, analyzer: Analyzer, module: SourceModule) -> None:
        self.a = analyzer
        self.m = module
        self.aliases: dict[str, str] = {}
        self.routers: set[str] = set()
        self.callbacks: set[ast.AST] = set()

    def run(self) -> None:
        for stmt in self.m.tree.body:
            self._collect(stmt)
        for stmt in self.m.tree.body:
            self._declare(stmt)
        self._scan(self.m.tree, None)

    def report(self, node: ast.AST, code: str, message: str) -> None:
        self.a.report(self.m, node, code, message)

    # --- имена ---
    def qual(self, node: ast.AST | None) -> str | None:
        """Полное имя выражения с учётом импортов: ``events.TakeDamage`` → ``amxpy.events.TakeDamage``."""
        if isinstance(node, ast.Name):
            name = self.aliases.get(node.id, node.id)
        elif isinstance(node, ast.Attribute):
            base = self.qual(node.value)
            if base is None:
                return None
            name = f"{base}.{node.attr}"
        elif isinstance(node, ast.Constant) and node.value is None:
            return "None"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):  # аннотация строкой
            try:
                return self.qual(ast.parse(node.value, mode="eval").body)
            except SyntaxError:
                return None
        else:
            return None
        return _CANON.get(name, name)

    def _collect(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    self.aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    self.aliases[top] = top
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.level == 0 and stmt.module:  # относительные импорты — модули самого плагина
                for alias in stmt.names:
                    self.aliases[alias.asname or alias.name] = f"{stmt.module}.{alias.name}"
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and isinstance(stmt.value, ast.Call):
            kind = self.qual(stmt.value.func)
            if kind in ("amxpy.Plugin", "amxpy.Router"):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                self.routers.update(t.id for t in targets if isinstance(t, ast.Name))
                if kind == "amxpy.Plugin":
                    self.a.plugins.append((self.m, stmt.value))
        elif isinstance(stmt, (ast.If, ast.Try, ast.With)):
            for part in (getattr(stmt, "body", []), getattr(stmt, "orelse", []), getattr(stmt, "finalbody", [])):
                for inner in part:
                    self._collect(inner)
            for handler in getattr(stmt, "handlers", []):
                for inner in handler.body:
                    self._collect(inner)

    # --- декларации ---
    def _declare(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._function(stmt)
        elif isinstance(stmt, ast.ClassDef):
            self._config_class(stmt)
        for node in _scope([stmt]):
            if isinstance(node, ast.Call) and self._router_call(node.func) == "forward":
                self._forward(node)

    def _router_call(self, func: ast.AST) -> str | None:
        """``router.<метод>`` для известных Plugin/Router этого модуля."""
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id in self.routers:
            return func.attr
        return None

    def _function(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for dec in fn.decorator_list:
            call = dec if isinstance(dec, ast.Call) else None
            method = self._router_call(call.func if call is not None else dec)
            if method not in _ROUTER_METHODS:
                continue
            self.callbacks.add(fn)
            if method == "on":
                self._event_handler(fn, dec, call)
            elif method == "command":
                self._command(fn, dec, call)
            elif method == "server_command":
                self._server_command(fn, dec, call)
            elif method == "native":
                self._native(fn, call)

    def _event_handler(self, fn: ast.FunctionDef | ast.AsyncFunctionDef, dec: ast.AST, call: ast.Call | None) -> None:
        if call is None or not call.args:
            self.report(dec, "AMX100", "укажите событие: @plugin.on(events.Имя)")
            return
        qual = self.qual(call.args[0]) or ""
        name = qual.rsplit(".", 1)[-1]
        if not qual.startswith("amxpy.events."):
            self.report(call.args[0], "AMX100", "ожидается класс события из amxpy.events")
            return
        cls = CATALOG.get(name)
        if cls is None:
            self.report(call.args[0], "AMX100", f"неизвестное событие {name}{_suggest(name, CATALOG)}")
            return
        post: Any = cls.phases[0]  # без post= — первая фаза события
        for kw in call.keywords:
            if kw.arg == "post":
                post = _literal(kw.value)
                if not isinstance(post, bool):
                    self.report(kw.value, "AMX108", "post должен быть True или False")
                    return
            elif kw.arg not in ("priority",) and kw.arg not in cls.fields():
                self.report(kw.value, "AMX108", f"у {name} нет поля {kw.arg!r} для фильтра{_suggest(str(kw.arg), cls.fields())}")
        if post not in cls.phases:
            self.report(call, "AMX107", f"у события {name} нет {'post' if post else 'pre'}-фазы")
            return
        self.a.decl.events.append({"event": name, "post": post})
        self._check_handler(fn, cls, post)

    def _check_handler(self, fn: ast.FunctionDef | ast.AsyncFunctionDef, cls: Any, post: bool) -> None:
        params = fn.args.posonlyargs + fn.args.args
        if len(params) != 1 or fn.args.vararg is not None:
            self.report(fn, "AMX102", "обработчик события принимает один аргумент — событие")
            return
        ev = params[0].arg
        fields = cls.fields()
        public = {n for n in dir(cls) if not n.startswith("_")}
        awaits = [(n.lineno, n.col_offset) for n in _scope(fn.body) if isinstance(n, ast.Await)]
        first_await = min(awaits) if awaits else None
        used_after_await = False
        for node in sorted(_scope(fn.body), key=lambda n: (getattr(n, "lineno", 0), getattr(n, "col_offset", 0))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == ev:
                attr = node.attr
                if attr not in public:
                    self.report(node, "AMX101", f"у {cls.__name__} нет поля {attr!r}{_suggest(attr, public)}")
                elif isinstance(node.ctx, ast.Store):
                    field_ = fields.get(attr)
                    if attr == "result" and not cls.has_result:
                        self.report(node, "AMX106", f"{cls.__name__} не возвращает результата")
                    elif field_ is not None and not field_.mutable:
                        self.report(node, "AMX106", f"{cls.__name__}.{attr} только для чтения")
                    elif post:
                        self.report(node, "AMX105", "в post-обработчике изменение события ни на что не влияет")
                elif attr == "cancel" and not cls.cancellable:
                    self.report(node, "AMX106", f"{cls.__name__} нельзя отменить")
                elif attr == "cancel" and post:
                    self.report(node, "AMX105", "в post-обработчике отменять поздно")
            if (
                first_await is not None
                and not used_after_await
                and isinstance(node, ast.Name)
                and node.id == ev
                and (node.lineno, node.col_offset) > first_await
            ):
                used_after_await = True
                self.report(
                    node,
                    "AMX104",
                    "событие используется после await, когда оно уже недействительно — скопируйте нужные поля до первого await",
                )

    def _usage(self, command: str, fn: ast.FunctionDef | ast.AsyncFunctionDef, *, skip_first: bool) -> str:
        params = fn.args.posonlyargs + fn.args.args
        first_default = len(params) - len(fn.args.defaults)
        parts = [command]
        for i, p in enumerate(params):
            if skip_first and i == 0:
                continue
            optional = i >= first_default or self._optional(p.annotation)
            parts.append(f"[{p.arg}]" if optional else f"<{p.arg}>")
        if fn.args.vararg is not None:
            parts.append(f"[{fn.args.vararg.arg}...]")
        return " ".join(parts)

    def _optional(self, ann: ast.AST | None) -> bool:
        if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
            return self.qual(ann.left) == "None" or self.qual(ann.right) == "None"
        if isinstance(ann, ast.Subscript):
            return (self.qual(ann.value) or "").endswith("Optional")
        return False

    def _command(self, fn: ast.FunctionDef | ast.AsyncFunctionDef, dec: ast.AST, call: ast.Call | None) -> None:
        if call is None or not call.args:
            self.report(dec, "AMX401", 'укажите имя команды: @plugin.command("/hp")')
            return
        names: list[str] = []
        for arg in call.args:
            name = _literal(arg)
            if not isinstance(name, str):
                self.report(arg, "AMX401", "имя команды должно быть строкой-литералом")
            elif not (CHAT_COMMAND_RE.match(name) or CONSOLE_COMMAND_RE.match(name)):
                self.report(arg, "AMX401", f"недопустимое имя команды {name!r}")
            elif name.lower() in self.a.command_names:
                self.report(arg, "AMX403", f"команда {name} объявлена дважды")
            else:
                self.a.command_names.add(name.lower())
                names.append(name)
        if not names:
            return
        if not (fn.args.posonlyargs + fn.args.args):
            self.report(fn, "AMX402", "первый параметр обработчика команды — игрок, который её вызвал")
            return
        options = {kw.arg: kw.value for kw in call.keywords}
        help_text = _literal(options.get("help"))
        self.a.decl.commands.append(
            {
                "names": names,
                "usage": self._usage(names[0], fn, skip_first=True),
                "help": help_text if isinstance(help_text, str) else "",
                "access": ast.unparse(options["access"]) if "access" in options else "",
            }
        )

    def _server_command(self, fn: ast.FunctionDef | ast.AsyncFunctionDef, dec: ast.AST, call: ast.Call | None) -> None:
        name = _literal(call.args[0]) if call is not None and call.args else _MISSING
        if not isinstance(name, str) or not CONSOLE_COMMAND_RE.match(name):
            self.report(dec, "AMX401", "имя серверной команды должно быть строкой-литералом из латиницы")
            return
        if name.lower() in self.a.command_names:
            self.report(dec, "AMX403", f"команда {name} объявлена дважды")
            return
        self.a.command_names.add(name.lower())
        assert call is not None
        help_text = _literal(next((kw.value for kw in call.keywords if kw.arg == "help"), None))
        self.a.decl.server_commands.append(
            {
                "name": name,
                "usage": self._usage(name, fn, skip_first=False),
                "help": help_text if isinstance(help_text, str) else "",
            }
        )

    def _pawn_code(self, ann: ast.AST | None, *, result: bool = False) -> str | None:
        qual = self.qual(ann)
        if result and qual == "None":
            return "v"
        return _PAWN_CODES.get(qual or "")

    def _native(self, fn: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call | None) -> None:
        name: Any = fn.name
        if call is not None:
            for node in [*call.args[:1], *(kw.value for kw in call.keywords if kw.arg == "name")]:
                name = _literal(node)
        if not isinstance(name, str) or not NAME_RE.match(name):
            self.report(fn, "AMX204", f"недопустимое имя натива {name!r}")
            return
        if isinstance(fn, ast.AsyncFunctionDef):
            self.report(fn, "AMX203", "натив не может быть async: Pawn ждёт ответ сразу")
            return
        if fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs:
            self.report(fn, "AMX201", "у натива только позиционные параметры")
            return
        if name in self.a.native_names:
            self.report(fn, "AMX202", f"натив {name} объявлен дважды")
            return
        params = fn.args.posonlyargs + fn.args.args
        defaults = dict(zip([p.arg for p in params][len(params) - len(fn.args.defaults) :], fn.args.defaults))
        out_params: list[list[str]] = []
        out_defaults: dict[str, Any] = {}
        ok = True
        for p in params:
            code = self._pawn_code(p.annotation)
            if p.annotation is None:
                self.report(p, "AMX201", f"параметр {p.arg}: укажите тип (int, float, bool, str или Player)")
                ok = False
            elif code is None:
                self.report(p.annotation, "AMX201", f"тип {ast.unparse(p.annotation)} не переводится в Pawn (int, float, bool, str, Player)")
                ok = False
            else:
                out_params.append([p.arg, code])
                if p.arg in defaults:
                    value = _literal(defaults[p.arg])
                    if value is not _MISSING and code in "ifbs":
                        out_defaults[p.arg] = value
        if fn.returns is None:
            self.report(fn, "AMX205", f"натив {name}: укажите тип результата (-> int, -> None ...)")
            returns: str | None = "v"
        else:
            returns = self._pawn_code(fn.returns, result=True)
            if returns is None:
                self.report(fn.returns, "AMX201", f"тип {ast.unparse(fn.returns)} не переводится в Pawn")
                ok = False
        if not ok:
            return
        self.a.native_names.add(name)
        self.a.decl.natives.append(
            {
                "name": name,
                "params": out_params,
                "returns": returns,
                "defaults": out_defaults,
                "doc": ast.get_docstring(fn) or "",
            }
        )

    def _forward(self, call: ast.Call) -> None:
        name = _literal(call.args[0]) if call.args else _MISSING
        if not isinstance(name, str) or not NAME_RE.match(name):
            self.report(call, "AMX206", "имя форварда должно быть строкой-литералом из латиницы")
            return
        if name in self.a.forward_names:
            self.report(call, "AMX202", f"форвард {name} объявлен дважды")
            return
        params: list[list[str]] = []
        items = [(f"arg{i}", node) for i, node in enumerate(call.args[1:], 1)]
        items += [(str(kw.arg), kw.value) for kw in call.keywords if kw.arg]
        for pname, node in items:
            code = self._pawn_code(node)
            if code is None:
                self.report(node, "AMX201", f"тип {ast.unparse(node)} не переводится в Pawn (int, float, bool, str, Player)")
                return
            params.append([pname, code])
        self.a.forward_names.add(name)
        self.a.decl.forwards.append({"name": name, "params": params})

    def _config_class(self, cls: ast.ClassDef) -> None:
        if not any(self.qual(base) == "amxpy.Config" for base in cls.bases):
            return
        prefix: Any = ""
        for kw in cls.keywords:
            if kw.arg == "prefix":
                prefix = _literal(kw.value)
                if not isinstance(prefix, str):
                    self.report(kw.value, "AMX404", "prefix должен быть строкой-литералом")
                    return
        for stmt in cls.body:
            if not (
                isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
                and isinstance(stmt.value, ast.Call)
                and self.qual(stmt.value.func) == "amxpy.cvar"
            ):
                continue
            self._cvar(stmt, stmt.target.id, prefix, stmt.value)

    def _cvar(self, stmt: ast.AnnAssign, attr: str, prefix: str, call: ast.Call) -> None:
        type_name = self.qual(stmt.annotation) or ""
        tp = _CVAR_TYPES.get(type_name)
        if tp is None:
            self.report(stmt.annotation, "AMX404", "тип cvar'а: bool, int, float или str")
            return
        options = {kw.arg: kw.value for kw in call.keywords}
        default = _literal(call.args[0] if call.args else None)
        description = _literal(call.args[1] if len(call.args) > 1 else options.get("description"))
        if default is _MISSING:
            self.report(call, "AMX405", "значение по умолчанию должно быть литералом")
            return
        valid = (
            isinstance(default, bool)
            if tp is bool
            else isinstance(default, (int, float)) and not isinstance(default, bool)
            if tp is float
            else isinstance(default, tp) and not isinstance(default, bool)
        )
        if not valid:
            self.report(call.args[0], "AMX405", f"значение {default!r} не подходит под тип {type_name}")
            return
        explicit = _literal(options.get("name"))
        name = explicit if isinstance(explicit, str) else prefix + attr
        if not _CVAR_NAME_RE.match(name):
            self.report(stmt, "AMX406", f"недопустимое имя cvar'а {name!r}")
            return
        if name in self.a.cvar_names:
            self.report(stmt, "AMX406", f"cvar {name} объявлен дважды")
            return
        self.a.cvar_names.add(name)
        bounds = {key: _literal(options.get(key)) for key in ("min", "max")}
        self.a.decl.cvars.append(
            {
                "name": name,
                "type": type_name,
                "default": format_value(tp, default),
                "description": description if isinstance(description, str) else "",
                "min": bounds["min"] if isinstance(bounds["min"], (int, float)) else None,
                "max": bounds["max"] if isinstance(bounds["max"], (int, float)) else None,
            }
        )

    # --- вызовы: блокирующие и при импорте ---
    def _scan(self, node: ast.AST, func: ast.AST | None) -> None:
        if isinstance(node, ast.Call):
            self._check_call(node, func)
        for child in ast.iter_child_nodes(node):
            inner = child if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) else func
            self._scan(child, inner)

    def _check_call(self, call: ast.Call, func: ast.AST | None) -> None:
        qual = self.qual(call.func)
        if qual is None:
            return
        if func is None:
            if qual in _IMPORT_TIME:
                self.report(
                    call,
                    "AMX301",
                    f"{qual}() выполняется при импорте модуля; перенесите в обработчик events.Init — "
                    "иначе это мешает горячей перезагрузке",
                )
        elif qual in _BLOCKING and (isinstance(func, ast.AsyncFunctionDef) or func in self.callbacks):
            self.report(call, "AMX103", f"{qual}() блокирует кадр сервера; используйте {_BLOCKING[qual]}")

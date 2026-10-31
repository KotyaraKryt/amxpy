"""Хост рантайма: загрузка плагинов, рассылка событий, команды, нативы, горячая перезагрузка.

Один хост на процесс. На сервере его создаёт :mod:`amxpy._entry` по вызову
C++-модуля, в тестах — :class:`amxpy.testing.FakeServer`.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import gc
import importlib
import inspect
import logging
import math
import pickle
import struct
import sys
import textwrap
import threading
import typing
import tomllib
import weakref
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import _backend as B
from . import _state, context, loader, texts
from ._bridge import build_amxx, build_forwards_image, forward_names
from .commands import ArgError, Signature, _unwrap_optional, tokenize
from .config import FCVAR_PROTECTED, FCVAR_SERVER, Config, render_cfg
from .events import (
    HOOKS,
    Authorized,
    Connect,
    Disconnected,
    Event,
    Frame,
    Init,
    MapEnd,
    MapStart,
    PutInServer,
    Say,
    Unload,
)
from .loop import FrameLoop
from .amxx import Bridge, FloatRef, Ref
from .menu import Menu, MenuItem
from .message import utf8_chunks
from .package import PackageError, PluginPackage, read_package
from .player import Entity, Player, PlayerState
from .plugin import (
    CommandSpec,
    Forward,
    HandlerSpec,
    NativeSpec,
    PeriodicSpec,
    Plugin,
    Router,
    ServerCommandSpec,
)

VERSION = "0.1.0"
log = logging.getLogger("amxpy")

_PENDING_AUTH = ("", "STEAM_ID_PENDING", "VALVE_ID_PENDING")
_DEFAULT_RESULT = {"v": 0, "i": 0, "b": 0, "f": 0.0, "s": "", "p": 0}


class PluginLoadError(Exception):
    """Плагин не загружен; причина уже записана в журнал."""


def _mtime(path: Path | None) -> float | None:
    try:
        return path.stat().st_mtime if path is not None else None
    except OSError:
        return None


def _encode(code: str, value: Any) -> Any:
    """Значение Python → значение для Pawn по коду типа."""
    if code == "p":
        return value.index if value is not None else 0
    if code == "b":
        return 1 if value else 0
    if code == "i":
        return int(value) if value is not None else 0
    if code == "f":
        return float(value) if value is not None else 0.0
    if code == "s":
        return "" if value is None else str(value)
    return 0


@dataclass(frozen=True)
class Snapshot:
    """Состояние плагина для горячей перезагрузки: PlayerState(keep=True) и значения keep()."""

    states: bytes | None
    kept: bytes | None


class PluginInstance:
    """Загруженный плагин: его код, всё, что он зарегистрировал, и его задачи."""

    def __init__(self, host: Host, pkg: PluginPackage, path: Path | None) -> None:
        self.host = host
        self.package = pkg
        self.manifest = pkg.manifest
        self.name = pkg.name
        self.path = path
        self.mtime = _mtime(path)
        self.plugin: Plugin | None = None
        self.module: Any = None
        self.states: list[PlayerState[Any]] = []
        self.configs: list[Config] = []
        self.natives: dict[str, NativeSpec] = {}
        self.tasks: set[asyncio.Task[Any]] = set()
        self.kept: dict[str, Any] = {}
        self.kept_blob: bytes | None = None  # keep() прошлой версии — распаковывается при первом kept()
        self._restored: dict[str, Any] | None = None
        self.unload_callbacks: list[Callable[[], Any]] = []
        self.status = "loading"
        self.errors = 0
        self.log = logging.getLogger(f"amxpy.{self.name}")
        self._translations: dict[str, dict[str, Any]] | None = None

    @property
    def restored(self) -> dict[str, Any]:
        """Значения keep() прошлой версии; лениво — kept() работает и при импорте модуля."""
        if self._restored is None:
            self._restored = {}
            if self.kept_blob is not None:
                try:
                    self._restored = pickle.loads(self.kept_blob)
                except Exception:
                    self.log.exception("cannot restore kept values after the reload")
        return self._restored

    def __repr__(self) -> str:
        return f"<PluginInstance {self.name} {self.status}>"

    def config_file(self, name: str, default: str) -> Path:
        """addons/amxpy/configs/<плагин>/<name>; создаётся из default, если его нет, и не перезаписывается."""
        rel = PurePosixPath(name)
        if "\\" in name or not rel.parts or rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"config file must be a path inside the plugin folder, got {name!r}")
        path = self.host.base_dir.joinpath("configs", self.name, *rel.parts)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(default).lstrip("\n"), encoding="utf-8")
            self.log.info("created %s", path)
        return path

    def attach_plugin(self, plugin: Plugin) -> None:
        if self.plugin is not None:
            raise RuntimeError(f"{self.name}: Plugin(...) is created twice")
        self.plugin = plugin

    def report(self, where: str, exc: BaseException | None = None) -> None:
        self.errors += 1
        self.log.error("error in %s", where, exc_info=exc if exc is not None else True)

    def translate(self, lang: str, key: str, **params: Any) -> str:
        """Строка из data/lang/<язык>.toml: язык игрока → en → любой → сам ключ."""
        if self._translations is None:
            self._translations = {}
            for name, blob in self.package.data.items():
                if name.startswith("lang/") and name.endswith(".toml"):
                    try:
                        self._translations[name[5:-5]] = tomllib.loads(blob.decode("utf-8"))
                    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
                        self.log.error("broken translation file %s: %s", name, exc)
        for table in (self._translations.get(lang), self._translations.get("en"), *self._translations.values()):
            if table and key in table:
                try:
                    return str(table[key]).format(**params)
                except (KeyError, IndexError, ValueError) as exc:
                    self.log.warning("translation %s: bad placeholder %s", key, exc)
                    return str(table[key])
        return key


class _Handler:
    __slots__ = ("instance", "spec", "label")

    def __init__(self, instance: PluginInstance, spec: HandlerSpec) -> None:
        self.instance = instance
        self.spec = spec
        self.label = f"{spec.event.__name__} handler {spec.fn.__qualname__}"


class _Command:
    __slots__ = ("instance", "spec", "signature", "used")

    def __init__(self, instance: PluginInstance, spec: CommandSpec, signature: Signature) -> None:
        self.instance = instance
        self.spec = spec
        self.signature = signature
        self.used: weakref.WeakKeyDictionary[Player, float] = weakref.WeakKeyDictionary()


class _ServerCommand:
    __slots__ = ("instance", "spec", "signature")

    def __init__(self, instance: PluginInstance, spec: ServerCommandSpec, signature: Signature) -> None:
        self.instance = instance
        self.spec = spec
        self.signature = signature


class _OpenMenu:
    """Меню amxpy, открытое у игрока."""

    __slots__ = ("menu", "page", "slots", "inst", "future", "expires")

    def __init__(self, menu: Menu, page: int, slots: dict[int, Any], inst: PluginInstance | None,
                 future: asyncio.Future[Any] | None, expires: float | None) -> None:  # fmt: skip
        self.menu = menu
        self.page = page
        self.slots = slots
        self.inst = inst
        self.future = future
        self.expires = expires

    def resolve(self, value: Any) -> None:
        if self.future is not None and not self.future.done():
            self.future.set_result(value)


_PAWN_CODES: dict[Any, str] = {int: "i", bool: "b", float: "f", str: "s", Player: "p", Ref: "r", FloatRef: "q"}


def _pawn_codes(fn: Callable[..., Any]) -> str:
    """Разметка аргументов подписчика Pawn-форварда по аннотациям; без аннотации — целое."""
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    codes = []
    for param in inspect.signature(fn).parameters.values():
        if param.kind not in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            break
        _, ann = _unwrap_optional(hints.get(param.name, int))
        codes.append(_PAWN_CODES.get(ann, "i"))
    return "".join(codes)


def _float_cell(value: float) -> int:
    return struct.unpack("<i", struct.pack("<f", float(value)))[0]


class _LogHandler(logging.Handler):
    """Журнал рантайма и плагинов → консоль и логи сервера."""

    def __init__(self, backend: B.Backend) -> None:
        super().__init__()
        self.backend = backend
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            plugin = record.name[6:] if record.name.startswith("amxpy.") else ""
            prefix = f"[amxpy] [{plugin}] " if plugin else "[amxpy] "
            if record.levelno >= logging.ERROR:
                level = B.LOG_ERROR
            elif record.levelno >= logging.WARNING:
                level = B.LOG_WARNING
            else:
                level = B.LOG_INFO
            self.backend.log(level, prefix + self.format(record))
        except Exception:
            self.handleError(record)


class Host:
    def __init__(
        self,
        backend: B.Backend,
        *,
        clock: Callable[[], float] | None = None,
        game_dir: str | Path | None = None,
    ) -> None:
        self.backend = backend
        self.loop = FrameLoop(clock)
        self.importer = loader.PluginImporter()
        self.game_dir = Path(game_dir if game_dir is not None else backend.game_dir())
        self.base_dir = self.game_dir / "addons" / "amxpy"
        self.instances: dict[str, PluginInstance] = {}
        self.players: dict[int, Player] = {}
        self._handlers: dict[tuple[type[Event], bool], list[_Handler]] = {}
        self._commands: dict[str, _Command] = {}
        self._server_commands: dict[str, _ServerCommand] = {}
        self._engine_commands: set[str] = set()
        self._natives: dict[str, str] = {}  # натив → имя плагина
        self._forwards: dict[str, tuple[PluginInstance, Forward]] = {}
        self._subscribers: dict[str, list[tuple[PluginInstance, Callable[..., Any], str]]] = {}  # (плагин, fn, разметка)
        self._pawn_written: list[str] = []  # форварды в amxpy_forwards.amxx на диске
        self._pawn_active: list[str] = []  # форварды плагина-приёмника, загруженного AMXX на этой карте
        self._hook_users: Counter[str] = Counter()
        self._missing_hooks: set[str] = set()
        self._waiters: dict[type[Event], list[tuple[asyncio.Future[Any], Any, PluginInstance | None]]] = {}
        self._executor: ThreadPoolExecutor | None = None
        self.inflight = 0  # задачи offload() в работе
        self._log_handler: _LogHandler | None = None
        self._initialized = False  # Init разослан (первая карта запущена)
        self._next_poll = 0.0
        self._next_watch = 0.0
        self.game_thread = threading.get_ident()  # нативы AMXX — только из него
        self.amxx = Bridge(self)

    @property
    def plugins_dir(self) -> Path:
        return self.base_dir / "plugins"

    # ------------------------------------------------------------------ жизненный цикл

    def start(self) -> None:
        if _state.host is not None:
            raise RuntimeError("an amxpy host is already running in this process")
        _state.host = self
        self._log_handler = _LogHandler(self.backend)
        log.addHandler(self._log_handler)
        log.setLevel(logging.INFO)
        log.propagate = False
        self.loop.attach()
        self.loop.set_task_factory(self._task_factory)
        self.loop.set_exception_handler(self._loop_exception)
        sys.meta_path.insert(0, self.importer)
        self.backend.cvar_register("amxpy_version", VERSION, FCVAR_SERVER)
        self.backend.cvar_register("amxpy_hotreload", "1", 0)
        self._engine_command("amxpy")

    def shutdown(self) -> None:
        for name in reversed(list(self.instances)):
            self._unload(self.instances[name], "shutdown")
        for _ in range(3):  # отменённые задачи дорабатывают свои finally
            self.loop.tick()
        pending = asyncio.all_tasks(self.loop)
        for task in pending:
            task.cancel()
        if pending:
            self.loop.tick()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self.loop.detach()
        self.loop.close()
        if self.importer in sys.meta_path:
            sys.meta_path.remove(self.importer)
        if self._log_handler is not None:
            log.removeHandler(self._log_handler)
        _state.host = None

    def boot(self) -> None:
        """Загрузить плагины из addons/amxpy/plugins.ini."""
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        ini = self.base_dir / "plugins.ini"
        if not ini.exists():
            ini.write_text("; amxpy: plugin packages to load, one per line (addons/amxpy/plugins/)\n", encoding="utf-8")
        for raw in ini.read_text(encoding="utf-8").splitlines():
            line = raw.split(";", 1)[0].split("//", 1)[0].strip()
            if line:
                try:
                    self.load_file(line)
                except PluginLoadError:
                    pass
        self._update_forwards_plugin(force=True)  # убрать приёмник прошлого запуска, если подписок нет

    # ------------------------------------------------------------------ загрузка и выгрузка

    def load_file(self, name: str | Path) -> PluginInstance:
        path = Path(name)
        if not path.is_absolute():
            path = self.plugins_dir / path
        if not path.suffix:
            path = path.with_suffix(".amxpy")
        try:
            pkg = read_package(path)
        except PackageError as exc:
            log.error("cannot load %s: %s", path.name, exc)
            raise PluginLoadError(str(exc)) from None
        return self.load_package(pkg, path)

    def load_package(
        self, pkg: PluginPackage, path: Path | None = None, *, blob: Snapshot | None = None, hot: bool = False
    ) -> PluginInstance:
        try:
            pkg.check_runtime()
            if pkg.name in self.instances:
                raise PackageError(f"{pkg.name} is already loaded")
        except PackageError as exc:
            log.error("cannot load %s: %s", pkg.name, exc)
            raise PluginLoadError(str(exc)) from None

        inst = PluginInstance(self, pkg, path)
        if blob is not None:
            inst.kept_blob = blob.kept
        self.importer.mount(pkg)
        token = context.current.set(inst)
        try:
            inst.module = importlib.import_module(loader.module_name(pkg.name))
            if inst.plugin is None:
                raise PluginLoadError(f"{pkg.name}: the package does not create Plugin(...)")
            self.instances[inst.name] = inst
            self._activate(inst)
            self._restore(inst, blob)
        except (Exception, SystemExit) as exc:
            if self.instances.get(inst.name) is inst:
                del self.instances[inst.name]
            self._deactivate(inst)
            self.importer.unmount(pkg.name)
            if isinstance(exc, PluginLoadError):
                log.error("cannot load %s", exc)
            else:
                log.error("cannot load %s", pkg.name, exc_info=exc)
            raise PluginLoadError(f"{pkg.name}: {exc}") from exc
        finally:
            context.current.reset(token)

        inst.status = "running"
        plugin = inst.plugin
        log.info("loaded %s %s by %s", plugin.name, plugin.version, plugin.author or "unknown")
        if self._initialized or hot:
            self.dispatch(Init, [hot], only=inst)
            if self._initialized:
                self.dispatch(MapStart, [self.backend.map_name()], only=inst)
        return inst

    def unload(self, name: str) -> bool:
        inst = self.instances.get(name)
        if inst is None:
            log.error("plugin %s is not loaded", name)
            return False
        self._unload(inst, "unload")
        return True

    def reload(self, name: str, package: PluginPackage | None = None) -> bool:
        """Горячая перезагрузка с переносом состояния; при ошибке — откат на старую версию."""
        inst = self.instances.get(name)
        if inst is None:
            log.error("plugin %s is not loaded", name)
            return False
        try:
            if package is None:
                if inst.path is None:
                    raise PackageError(f"{name} was not loaded from a file")
                package = read_package(inst.path)
            package.check_runtime()
            if package.name != name:
                raise PackageError(f"the package is {package.name}, not {name}")
        except PackageError as exc:
            log.error("reload %s: %s", name, exc)
            return False
        conflict = self._native_conflict(inst.manifest, package.manifest)
        if conflict:
            log.error("reload %s refused: %s; restart the server to apply it", name, conflict)
            return False

        old_package, path = inst.package, inst.path
        old_module = weakref.ref(inst.module) if inst.module is not None else None
        blob = self._unload(inst, "reload", snapshot=True)
        del inst
        try:
            new = self.load_package(package, path, blob=blob, hot=True)
            if new.errors:
                raise PluginLoadError(f"{name}: {new.errors} error(s) while starting")
        except PluginLoadError as exc:
            if name in self.instances:
                self._unload(self.instances[name], "reload")
            log.error("reload of %s failed (%s); rolling back", name, exc)
            try:
                self.load_package(old_package, path, blob=blob, hot=True)
            except PluginLoadError:
                log.error("rollback of %s failed; the plugin is stopped", name)
            return False
        log.info("reloaded %s", name)
        if old_module is not None:
            self.loop.call_later(5.0, self._check_leak, name, old_module)
        return True

    def _unload(self, inst: PluginInstance, reason: str, *, snapshot: bool = False) -> Snapshot | None:
        """Остановить плагин; ``snapshot`` — вернуть состояние для перезагрузки.

        Снимок делается после Unload и on_unload, но до снятия модулей: так в нём есть и то,
        что плагин сохранил через ``keep()`` в on_unload (в async-колбэке — до первого await).
        """
        if inst.status == "stopped":
            return None
        inst.status = "stopping"
        self.dispatch(Unload, [reason], only=inst)
        for callback in inst.unload_callbacks:
            token = context.current.set(inst)
            try:
                result = callback()
            except (Exception, SystemExit):
                inst.report(f"unload callback {getattr(callback, '__qualname__', callback)!s}")
            else:
                if asyncio.iscoroutine(result):
                    # задача хоста, а не плагина: её не отменят вместе с задачами плагина
                    asyncio.Task(result, loop=self.loop, context=contextvars.Context(), eager_start=True)
            finally:
                context.current.reset(token)
        blob = self._snapshot(inst) if snapshot else None
        for player in list(self.players.values()):
            if player._menu is not None and player._menu.inst is inst:
                self.close_menu(player)
        for task in list(inst.tasks):
            task.cancel()
        self._deactivate(inst)
        if self.instances.get(inst.name) is inst:
            del self.instances[inst.name]
        self.importer.unmount(inst.name)
        inst.status = "stopped"
        log.info("unloaded %s (%s)", inst.name, reason)
        return blob

    @staticmethod
    def _native_conflict(old: dict[str, Any], new: dict[str, Any]) -> str | None:
        def signatures(manifest: dict[str, Any]) -> dict[str, tuple[str, str]]:
            return {
                n["name"]: ("".join(code for _, code in n["params"]), n["returns"])
                for n in manifest.get("natives", [])
            }

        before, after = signatures(old), signatures(new)
        for name in sorted(before.keys() & after.keys()):
            if before[name] != after[name]:
                return f"native {name} changed its signature"
        return None

    def _keepers(self, inst: PluginInstance) -> dict[str, PlayerState[Any]]:
        """PlayerState(keep=True) плагина по адресу «модуль:переменная»."""
        found: dict[str, PlayerState[Any]] = {}
        for modname in loader.plugin_modules(inst.name):
            for attr, value in list(vars(sys.modules[modname]).items()):
                if isinstance(value, PlayerState) and value.keep:
                    found[f"{modname}:{attr}"] = value
        return found

    def _snapshot(self, inst: PluginInstance) -> Snapshot:
        def dump(what: str, value: Any) -> bytes | None:
            try:
                return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
            except Exception:
                inst.log.exception("cannot save %s for the reload; it will be lost", what)
                return None

        states = {key: state._dump() for key, state in self._keepers(inst).items()}
        return Snapshot(dump("player state", states), dump("keep() values", inst.kept))

    def _restore(self, inst: PluginInstance, blob: Snapshot | None) -> None:
        if blob is None or blob.states is None:
            return
        try:
            states = pickle.loads(blob.states)  # классы берутся уже из новой версии плагина
        except Exception:
            inst.log.exception("cannot restore player state after the reload")
            return
        keepers = self._keepers(inst)
        for key, rows in states.items():
            state = keepers.get(key)
            if state is not None:
                state._restore(self.players, rows)

    def _check_leak(self, name: str, ref: weakref.ref[Any]) -> None:
        gc.collect()
        if ref() is not None:
            log.warning("the old version of %s is still referenced after the reload (memory leak?)", name)

    # ------------------------------------------------------------------ регистрация

    def _activate(self, inst: PluginInstance) -> None:
        seen: set[int] = set()
        configs: list[Config] = []

        def walk(component: Router | Config) -> None:
            if id(component) in seen:
                return
            seen.add(id(component))
            if isinstance(component, Config):
                configs.append(component)
                return
            for handler in component._handlers:
                self._add_handler(inst, handler)
            for command in component._commands:
                self._add_command(inst, command)
            for server_command in component._server_commands:
                self._add_server_command(inst, server_command)
            for native in component._natives:
                self._add_native(inst, native)
            for forward in component._forwards:
                self._forwards[forward.name] = (inst, forward)
            for name, fn in component._subscriptions:
                self._subscribers.setdefault(name, []).append((inst, fn, _pawn_codes(fn)))
            for periodic in component._periodic:
                self._start_periodic(inst, periodic)
            for sub in component._components:
                walk(sub)

        assert inst.plugin is not None
        walk(inst.plugin)
        for cfg in list(inst.configs):  # конфиги, созданные без include()
            walk(cfg)
        inst.configs = configs
        for cfg in configs:
            for spec in cfg.specs():
                flags = spec.flags | (FCVAR_PROTECTED if spec.protected else 0)
                self.backend.cvar_register(spec.name, spec.to_str(spec.default), flags)
        if configs:
            self._autoexec(inst, configs)
        self._update_forwards_plugin()

    def _deactivate(self, inst: PluginInstance) -> None:
        for key in list(self._handlers):
            handlers = self._handlers[key]
            kept = [h for h in handlers if h.instance is not inst]
            removed = len(handlers) - len(kept)
            if removed and key[0].hook:
                self._release_hook(key[0].hook, removed)
            if kept:
                self._handlers[key] = kept
            else:
                del self._handlers[key]
        self._commands = {k: c for k, c in self._commands.items() if c.instance is not inst}
        self._server_commands = {k: c for k, c in self._server_commands.items() if c.instance is not inst}
        self._natives = {k: owner for k, owner in self._natives.items() if owner != inst.name}
        self._forwards = {k: v for k, v in self._forwards.items() if v[0] is not inst}
        for name in list(self._subscribers):
            subscribers = [s for s in self._subscribers[name] if s[0] is not inst]
            if subscribers:
                self._subscribers[name] = subscribers
            else:
                del self._subscribers[name]
        self._update_forwards_plugin()
        for cls in list(self._waiters):
            waiters = []
            for waiter in self._waiters[cls]:
                if waiter[2] is inst:
                    waiter[0].cancel()
                else:
                    waiters.append(waiter)
            if waiters:
                self._waiters[cls] = waiters
            else:
                del self._waiters[cls]

    def _add_handler(self, inst: PluginInstance, spec: HandlerSpec) -> None:
        handlers = self._handlers.setdefault((spec.event, spec.post), [])
        handlers.append(_Handler(inst, spec))
        handlers.sort(key=lambda h: -h.spec.priority)  # сортировка устойчива: порядок загрузки сохраняется
        if spec.event.hook:
            self._acquire_hook(spec.event.hook)

    def _acquire_hook(self, hook: str) -> None:
        self._hook_users[hook] += 1
        if self._hook_users[hook] == 1 and not self.backend.enable_hook(hook, True):
            if hook not in self._missing_hooks:
                self._missing_hooks.add(hook)
                log.warning("hook %s is not available on this server (ReGameDLL required?)", hook)

    def _release_hook(self, hook: str, count: int) -> None:
        self._hook_users[hook] -= count
        if self._hook_users[hook] <= 0:
            del self._hook_users[hook]
            self.backend.enable_hook(hook, False)

    def _add_command(self, inst: PluginInstance, spec: CommandSpec) -> None:
        try:
            signature = Signature(spec.fn, with_caller=True)
        except (TypeError, NameError) as exc:
            inst.log.error("command %s: %s", spec.names[0], exc)
            return
        for name in spec.names:
            other = self._commands.get(name.lower())
            if other is not None and other.instance is not inst:
                inst.log.error("command %s is already registered by %s", name, other.instance.name)
                continue
            self._commands[name.lower()] = _Command(inst, spec, signature)

    def _add_server_command(self, inst: PluginInstance, spec: ServerCommandSpec) -> None:
        try:
            signature = Signature(spec.fn, with_caller=False)
        except (TypeError, NameError) as exc:
            inst.log.error("server command %s: %s", spec.name, exc)
            return
        key = spec.name.lower()
        other = self._server_commands.get(key)
        if other is not None and other.instance is not inst:
            inst.log.error("server command %s is already registered by %s", spec.name, other.instance.name)
            return
        self._server_commands[key] = _ServerCommand(inst, spec, signature)
        self._engine_command(key)

    def _engine_command(self, name: str) -> None:
        # команды движка нельзя удалить, поэтому регистрируются один раз на имя
        if name not in self._engine_commands:
            self._engine_commands.add(name)
            self.backend.register_server_command(name)

    def _add_native(self, inst: PluginInstance, spec: NativeSpec) -> None:
        owner = self._natives.get(spec.name)
        if owner is not None and owner != inst.name:
            inst.log.error("native %s is already provided by %s", spec.name, owner)
            return
        self._natives[spec.name] = inst.name
        inst.natives[spec.name] = spec
        if not self.backend.register_native(spec.name, spec.codes, spec.returns):
            # AMXX принимает нативы модуля только при его подключении — один раз за запуск сервера
            inst.log.warning("native %s will be available to Pawn plugins after a server restart", spec.name)

    def _start_periodic(self, inst: PluginInstance, spec: PeriodicSpec) -> None:
        async def run() -> None:
            await asyncio.sleep(spec.delay)
            while True:
                try:
                    result = spec.fn()
                    if inspect.isawaitable(result):
                        await result
                except asyncio.CancelledError:
                    raise
                except Exception:
                    inst.report(f"periodic task {spec.fn.__qualname__}")
                await asyncio.sleep(spec.seconds)

        token = context.current.set(inst)
        try:
            self._start(inst, run(), label=f"every {spec.fn.__qualname__}", eager=False)
        finally:
            context.current.reset(token)

    def _autoexec(self, inst: PluginInstance, configs: list[Config]) -> None:
        """Создать configs/<плагин>.cfg, если его нет, и выполнить его."""
        path = self.base_dir / "configs" / f"{inst.name}.cfg"
        try:
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                title = inst.plugin.name if inst.plugin is not None else inst.name
                rows = [spec.row() for cfg in configs for spec in cfg.specs()]
                path.write_text(render_cfg(title, rows), encoding="utf-8")
        except OSError as exc:
            inst.log.warning("cannot write %s: %s", path, exc)
            return
        try:
            relative = path.relative_to(self.game_dir).as_posix()
        except ValueError:
            relative = str(path)
        self.backend.server_command(f"exec {relative}")
        if self._initialized:  # при старте сервера конфиг выполнится вместе с буфером команд
            self.backend.server_execute()
        for cfg in configs:
            cfg._seen = {spec.attr: getattr(cfg, spec.attr) for spec in cfg.specs()}

    # ------------------------------------------------------------------ вызов кода плагинов

    def _call(
        self,
        inst: PluginInstance,
        fn: Callable[..., Any],
        *args: Any,
        scope: Player | None = None,
        label: str = "",
    ) -> Any:
        """Вызвать код плагина в его контексте; ошибки — в журнал, не наружу."""
        token = context.current.set(inst)
        try:
            result = fn(*args)
            if asyncio.iscoroutine(result):
                return self._start(inst, result, scope=scope, label=label)
            return result
        except (Exception, SystemExit):
            inst.report(label or getattr(fn, "__qualname__", repr(fn)))
            return None
        finally:
            context.current.reset(token)

    def _start(
        self,
        inst: PluginInstance,
        coro: Any,
        *,
        scope: Player | None = None,
        label: str = "",
        eager: bool = True,
    ) -> asyncio.Task[Any]:
        """Задача плагина; eager — код до первого await выполняется сразу (может влиять на событие)."""
        task = asyncio.Task(
            coro,
            loop=self.loop,
            context=contextvars.copy_context(),
            eager_start=eager,
            name=f"{inst.name}: {label}",
        )
        if task.done():
            self._finished(inst, label, task)
            return task
        inst.tasks.add(task)
        task.add_done_callback(inst.tasks.discard)
        if scope is not None:
            scope._tasks.add(task)
            task.add_done_callback(scope._tasks.discard)
        task.add_done_callback(functools.partial(self._finished, inst, label))
        return task

    @staticmethod
    def _finished(inst: PluginInstance, label: str, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            inst.report(label, exc)

    def _task_factory(self, loop: asyncio.AbstractEventLoop, coro: Any, **kwargs: Any) -> asyncio.Task[Any]:
        task = asyncio.Task(coro, loop=loop, **kwargs)
        inst = context.instance()  # задача принадлежит плагину, который её создал
        if inst is not None and not task.done():
            inst.tasks.add(task)
            task.add_done_callback(inst.tasks.discard)
        return task

    @staticmethod
    def _loop_exception(loop: asyncio.AbstractEventLoop, ctx: dict[str, Any]) -> None:
        log.error("asyncio: %s", ctx.get("message", "error"), exc_info=ctx.get("exception"))

    def spawn(self, coro: Any) -> asyncio.Task[Any]:
        inst = context.instance()
        if inst is None:
            return self.loop.create_task(coro)
        return self._start(inst, coro, label=getattr(coro, "__qualname__", "task"))

    async def offload(self, fn: Callable[..., Any], *args: Any) -> Any:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="amxpy")
        self.inflight += 1
        try:
            return await self.loop.run_in_executor(self._executor, functools.partial(fn, *args))
        finally:
            self.inflight -= 1

    async def wait_for(self, event: type[Event], *, check: Any = None, timeout: float | None = None) -> Any:
        future: asyncio.Future[Any] = self.loop.create_future()
        self._waiters.setdefault(event, []).append((future, check, context.instance()))
        if timeout is None:
            return await future
        async with asyncio.timeout(timeout):
            return await future

    # ------------------------------------------------------------------ события

    def dispatch(
        self,
        cls: type[Event],
        args: list[Any],
        *,
        post: bool = False,
        result: Any = None,
        only: PluginInstance | None = None,
    ) -> Event | None:
        """Разослать событие обработчикам одной фазы; вернуть событие (уже недействительное)."""
        handlers = self._handlers.get((cls, post))
        waiters = self._waiters.get(cls) if post == cls.phases[-1] else None
        if not handlers and not waiters:
            return None
        ev = cls(self, args, post, result)
        try:
            for handler in tuple(handlers or ()):
                if only is not None and handler.instance is not only:
                    continue
                if handler.spec.filters and not self._matches(handler, ev):
                    continue
                self._invoke(handler, ev)
                if ev._stopped:
                    break
            if waiters and only is None:
                self._resolve_waiters(cls, ev)
        finally:
            ev._expire()
        return ev

    def _matches(self, handler: _Handler, ev: Event) -> bool:
        try:
            return all(getattr(ev, k) == v for k, v in handler.spec.filters.items())
        except Exception:
            handler.instance.report(f"filter of {handler.label}")
            return False

    def _invoke(self, handler: _Handler, ev: Event) -> None:
        scope = getattr(ev, ev.scope) if ev.scope else None
        result = self._call(handler.instance, handler.spec.fn, ev, scope=scope, label=handler.label)
        if result is not None and not isinstance(result, asyncio.Task) and ev.has_result and not ev.post:
            ev.result = result  # «return значение» — ответ за игру

    def _resolve_waiters(self, cls: type[Event], ev: Event) -> None:
        snapshot = None
        remaining = []
        for waiter in self._waiters.get(cls, []):
            future, check, inst = waiter
            if future.done():
                continue
            if check is None:
                ok = True
            elif inst is not None:
                ok = bool(self._call(inst, check, ev, label="wait_for() check"))
            else:
                try:
                    ok = bool(check(ev))
                except Exception:
                    log.exception("wait_for() check failed")
                    ok = False
            if ok:
                if snapshot is None:
                    snapshot = ev._snapshot()
                future.set_result(snapshot)
            else:
                remaining.append(waiter)
        if remaining:
            self._waiters[cls] = remaining
        else:
            self._waiters.pop(cls, None)

    def on_event(self, hook: str, post: bool, args: Any, result: Any = None) -> tuple[bool, Any, Any] | None:
        """Хук C++-модуля. Ответ для pre: None — продолжить как есть;
        (True, значение, None) — заблокировать игру; (False, None, args) — продолжить с новыми аргументами."""
        cls = HOOKS.get(hook)
        if cls is None:
            return None
        ev = self.dispatch(cls, list(args), post=bool(post), result=result)
        if ev is None or ev.post:
            return None
        if ev._cancelled or ev._answered:
            return (True, ev._result if ev._answered else None, None)
        if ev._changed:
            return (False, None, ev._args)
        return None

    # ------------------------------------------------------------------ игроки

    def player_at(self, index: int) -> Player | None:
        player = self.players.get(index)
        return player if player is not None and not player._gone else None

    def entity_at(self, index: int) -> Player | Entity | None:
        if index <= 0:
            return None
        return self.player_at(index) or Entity(self, index)

    def find_player(self, query: str, *, strict: bool = False) -> Player | None:
        players = [p for p in self.players.values() if p.connected]
        text = query.strip()
        low = text.lower()
        if text.startswith("#") and text[1:].isdigit():
            found = [p for p in players if p.userid == int(text[1:])]
        elif low.startswith(("steam_", "valve_")):
            found = [p for p in players if p.steam_id.lower() == low]
        else:
            found = [p for p in players if p.name.lower() == low] or [p for p in players if low in p.name.lower()]
        if len(found) == 1:
            return found[0]
        if strict:
            raise ArgError("player_ambiguous" if found else "player_not_found", query=text)
        return None

    def on_client_connect(self, index: int, name: str, ip: str) -> str | None:
        """Возвращает причину отказа или None."""
        userid = self.backend.userid(index)
        player = self.players.get(index)
        if player is None or player._gone or player.userid != userid:
            if player is not None:
                self._forget(player)
            player = self.players[index] = Player(self, index, userid)
        # иначе тот же игрок переподключается после смены карты: хэндл и данные сохраняются
        ev = self.dispatch(Connect, [index, name, ip])
        if ev is not None and ev._answered and ev._result:
            self._forget(player)
            return str(ev._result)
        return None

    def on_client_putinserver(self, index: int) -> None:
        if self.player_at(index) is None:  # боты могут прийти без ClientConnect
            self.players[index] = Player(self, index, self.backend.userid(index))
        self.dispatch(PutInServer, [index])

    def on_client_disconnect(self, index: int) -> None:
        player = self.player_at(index)
        if player is not None:
            self.dispatch(Disconnected, [index])
            self._forget(player)

    def _forget(self, player: Player) -> None:
        player._gone = True
        if player._menu is not None:
            player._menu.resolve(None)
            player._menu = None
        for task in list(player._tasks):
            task.cancel()
        for inst in self.instances.values():
            for state in inst.states:
                state._drop(player)
        if self.players.get(player.index) is player:
            del self.players[player.index]

    def _sweep_players(self) -> None:
        # игрок, ушедший без ClientDisconnect (например, во время смены карты)
        for player in list(self.players.values()):
            if not player._gone and self.backend.userid(player.index) != player.userid:
                self._forget(player)

    # ------------------------------------------------------------------ команды

    def on_client_command(self, index: int, argv: list[str], args: str = "", handled: bool = False) -> bool:
        """True — команда обработана, игре её не передавать.

        ``handled`` — команду уже обработал другой плагин Metamod (например, AMXX своим меню)."""
        player = self.player_at(index)
        if player is None or not argv:
            return False
        name = argv[0].lower()
        if name == "menuselect":
            return self._menu_select(player, argv, handled)
        if name in ("say", "say_team"):
            text = args.strip()
            if len(text) >= 2 and text[0] == text[-1] == '"':
                text = text[1:-1].strip()
            ev = self.dispatch(Say, [index, text, name == "say_team"])
            hidden = ev is not None and ev.cancelled
            tokens = tokenize(text) if text[:1] in ("/", "!") else []
            command = self._commands.get(tokens[0].lower()) if tokens else None
            if command is None:
                return hidden
            self._run_command(command, player, tokens[0], tokens[1:])
            return hidden or command.spec.hide
        command = self._commands.get(name)
        if command is None:
            return False
        self._run_command(command, player, argv[0], list(argv[1:]))
        return True

    def _run_command(self, command: _Command, player: Player, name: str, tokens: list[str]) -> None:
        spec = command.spec
        lang = player.language
        if spec.access and not player.has_access(spec.access):
            player.print(texts.text("no_access", lang))
            return
        now = self.loop.time()
        if spec.cooldown:
            last = command.used.get(player)
            if last is not None and now - last < spec.cooldown:
                player.print(texts.text("cooldown", lang, seconds=math.ceil(spec.cooldown - (now - last))))
                return
        try:
            args = command.signature.parse(self, tokens)
        except ArgError as err:
            params = {"usage": command.signature.usage(name)} if err.key == "usage" else err.params
            player.print(texts.text(err.key, lang, **params))
            return
        if spec.cooldown:
            command.used[player] = now
        self._call(command.instance, spec.fn, player, *args, scope=player, label=f"command {name}")

    def on_server_command(self, argv: list[str]) -> None:
        if not argv:
            return
        name = argv[0].lower()
        if name == "amxpy":
            self._builtin(list(argv[1:]))
            return
        command = self._server_commands.get(name)
        if command is None:
            self.backend.server_print(f"[amxpy] {name}: no plugin handles this command\n")
            return
        try:
            args = command.signature.parse(self, list(argv[1:]))
        except ArgError as err:
            params = {"usage": command.signature.usage(name)} if err.key == "usage" else err.params
            self.backend.server_print(f"[amxpy] {texts.text(err.key, 'en', **params)}\n")
            return
        self._call(command.instance, command.spec.fn, *args, label=f"server command {name}")

    def _builtin(self, args: list[str]) -> None:
        def out(text: str) -> None:
            self.backend.server_print(text + "\n")

        def result(verb: str, ok: bool) -> None:
            # итог для rcon и amxpy deploy; подробности — в логе сервера
            out(f"[amxpy] {verb} {args[1]}: {'ok' if ok else 'failed, see the server log'}")

        sub = args[0].lower() if args else ""
        if sub == "list":
            out(f"[amxpy] {len(self.instances)} plugin(s):")
            for inst in self.instances.values():
                p = inst.plugin
                assert p is not None
                line = f"  {inst.name:<16} {p.version:<10} {inst.status:<8} {p.name}"
                if p.author:
                    line += f" ({p.author})"
                if inst.errors:
                    line += f", errors: {inst.errors}"
                out(line)
        elif sub == "version":
            out(f"[amxpy] {VERSION}, Python {sys.version.split()[0]}")
        elif sub == "load" and len(args) == 2:
            try:
                self.load_file(args[1])
            except PluginLoadError:
                result("load", False)
            else:
                result("load", True)
        elif sub == "unload" and len(args) == 2:
            result("unload", self.unload(args[1]))
        elif sub == "reload" and len(args) == 2:
            result("reload", self.reload(args[1]))
        else:
            out("usage: amxpy list | version | load <file> | unload <name> | reload <name>")

    # ------------------------------------------------------------------ меню

    def show_menu(self, player: Player, menu: Menu, page: int = 0, *, future: asyncio.Future[Any] | None = None) -> None:
        inst = context.instance()  # плагин, который показывает меню: в его контексте вызовутся пункты
        lang = player.language
        labels = {key: texts.text(f"menu_{key}", lang) for key in ("back", "next", "exit")}
        try:
            text, keys, slots, page = menu.render(player, page, labels)
        except Exception:
            if inst is not None:
                inst.report("menu rendering")
            else:
                log.exception("menu rendering failed")
            if future is not None and not future.done():
                future.set_result(None)
            return
        previous = player._menu
        if previous is not None and previous.future is not future:
            previous.resolve(None)  # меню заменили другим
        expires = self.loop.time() + menu.timeout if menu.timeout else None
        player._menu = _OpenMenu(menu, page, slots, inst, future, expires)
        self._send_menu(player, keys, text, int(menu.timeout) if menu.timeout else -1)

    def close_menu(self, player: Player, menu: Menu | None = None) -> None:
        state = player._menu
        if state is None or (menu is not None and state.menu is not menu):
            return
        player._menu = None
        state.resolve(None)
        if player.connected:
            self._send_menu(player, 0, "", 0)

    def _send_menu(self, player: Player, keys: int, text: str, seconds: int) -> None:
        msg_type = self.backend.user_message("ShowMenu")
        if not msg_type:
            log.warning("the ShowMenu message is not available yet")
            return
        chunks = utf8_chunks(text, 175) or [""]  # клиент принимает текст меню частями
        for i, chunk in enumerate(chunks):
            more = 1 if i < len(chunks) - 1 else 0
            data = [("s", keys), ("c", max(-1, min(seconds, 127))), ("b", more), ("S", chunk)]
            self.backend.send_message(B.MSG_ONE, msg_type, player.index, data)

    def _menu_select(self, player: Player, argv: list[str], handled: bool) -> bool:
        state = player._menu
        if state is None:
            return False
        if handled:  # нажатие забрало меню AMXX — значит, наше уже закрыто
            player._menu = None
            state.resolve(None)
            return False
        try:
            key = int(argv[1]) % 10  # клавиша 0 приходит как menuselect 10
        except (IndexError, ValueError):
            return False
        slot = state.slots.get(key)
        if slot is None:
            return True
        player._menu = None
        if state.expires is not None and self.loop.time() > state.expires:
            state.resolve(None)
            return True
        if slot in ("back", "next"):
            token = context.current.set(state.inst)
            try:
                self.show_menu(player, state.menu, state.page + (1 if slot == "next" else -1), future=state.future)
            finally:
                context.current.reset(token)
            return True
        if slot == "exit":
            state.resolve(None)
            return True
        item: MenuItem = slot
        state.resolve(item)
        if item.callback is not None:
            if state.inst is not None:
                self._call(state.inst, item.callback, player, scope=player, label="menu item")
            else:
                try:
                    item.callback(player)
                except Exception:
                    log.exception("menu item failed")
        return True

    # ------------------------------------------------------------------ нативы и форварды

    def native_specs(self) -> list[tuple[str, str, str, str]]:
        """(плагин, имя, коды параметров, код результата) — C++ регистрирует их в AMXX."""
        return [
            (inst.name, s.name, s.codes, s.returns) for inst in self.instances.values() for s in inst.natives.values()
        ]

    def call_native(self, name: str, args: Any) -> Any:
        owner = self._natives.get(name)
        inst = self.instances.get(owner) if owner is not None else None
        spec = inst.natives.get(name) if inst is not None else None
        if inst is None or spec is None:
            log.error("native %s is not available (its plugin is not loaded)", name)
            return 0
        values: list[Any] = []
        for (_, code), raw in zip(spec.params, args):
            if code == "p":
                player = self.player_at(int(raw))
                if player is None:  # не-игрок до функции не доходит
                    return _DEFAULT_RESULT[spec.returns]
                values.append(player)
            elif code == "b":
                values.append(bool(raw))
            elif code == "i":
                values.append(int(raw))
            elif code == "f":
                values.append(float(raw))
            else:
                values.append(str(raw))
        result = self._call(inst, spec.fn, *values, label=f"native {name}")
        return _encode(spec.returns, result)

    def emit_forward(self, forward: Forward, args: tuple[Any, ...]) -> int:
        encoded = tuple(_encode(code, value) for (_, code), value in zip(forward.params, args))
        for inst, fn, _ in list(self._subscribers.get(forward.name, ())):
            self._call(inst, fn, *args, label=f"forward {forward.name} subscriber")
        return int(self.backend.forward_execute(forward.name, forward.codes, encoded) or 0)

    # ------------------------------------------------------------------ Pawn-форварды

    def _update_forwards_plugin(self, *, force: bool = False) -> None:
        """Плагин-приёмник Pawn-форвардов (public на каждое имя подписки): AMXX грузит его с каждой картой."""
        names = forward_names([n for n in self._subscribers if n not in self._forwards])
        if names == self._pawn_written and not force:
            return
        amxmodx = self.game_dir / "addons" / "amxmodx"
        try:
            (amxmodx / "plugins").mkdir(parents=True, exist_ok=True)
            (amxmodx / "configs").mkdir(parents=True, exist_ok=True)
            ini = amxmodx / "configs" / "plugins-amxpy.ini"
            if names:
                image = build_forwards_image(names)
                (amxmodx / "plugins" / "amxpy_forwards.amxx").write_bytes(build_amxx([], image=image))
                ini.write_text("; amxpy: Pawn forwards for Python plugins (generated)\namxpy_forwards.amxx\n")
            else:
                ini.write_text("; amxpy: no Pawn forwards are subscribed (generated)\n")
        except OSError as exc:
            log.error("cannot write the Pawn forwards plugin: %s", exc)
            return
        self._pawn_written = names
        later = [n for n in names if n not in self._pawn_active]
        if later and self._initialized:
            log.info("Pawn forward(s) %s will reach Python from the next map", ", ".join(later))

    def on_pawn_forward(self, index: int, amx: int, args: list[int]) -> int:
        """Pawn-плагин выполнил форвард, на который подписан Python: public плагина-приёмника № index."""
        if not 0 <= index < len(self._pawn_active):
            return 0
        name = self._pawn_active[index]
        result = 0
        for inst, fn, codes in list(self._subscribers.get(name, ())):
            refs: list[tuple[Ref | FloatRef, int]] = []
            try:
                values = [self._pawn_value(code, raw, amx, refs) for code, raw in zip(codes, args)]
            except (IndexError, ValueError) as exc:
                inst.log.error("Pawn forward %s: bad arguments for %s: %s", name, fn.__qualname__, exc)
                continue
            answer = self._call(inst, fn, *values, label=f"Pawn forward {name}")
            for ref, address in refs:
                cell = _float_cell(ref.value) if isinstance(ref, FloatRef) else int(ref.value)
                self.backend.amx_write(amx, address, [cell])
            if isinstance(answer, (bool, int)):
                result = max(result, int(answer))
        return result

    def _pawn_value(self, code: str, raw: int, amx: int, refs: list[tuple[Ref | FloatRef, int]]) -> Any:
        if code == "b":
            return bool(raw)
        if code == "f":
            return struct.unpack("<f", struct.pack("<i", raw))[0]
        if code == "s":
            return self.backend.amx_string(amx, raw, 4096)
        if code == "p":
            return self.player_at(raw)
        if code in "rq":
            cell = self.backend.amx_read(amx, raw, 1)[0]
            ref: Ref | FloatRef = Ref(cell) if code == "r" else FloatRef(struct.unpack("<f", struct.pack("<i", cell))[0])
            refs.append((ref, raw))
            return ref
        return raw

    # ------------------------------------------------------------------ кадр и карта

    def on_frame(self) -> None:
        try:
            self.loop.tick()
        except Exception:
            log.exception("asyncio loop tick failed")
        for player in list(self.players.values()):
            if not player._authorized and not player._gone:
                auth = self.backend.player_auth(player.index)
                if auth not in _PENDING_AUTH:
                    player._authorized = True
                    self.dispatch(Authorized, [player.index, auth])
        now = self.loop.time()
        if now >= self._next_poll:
            self._next_poll = now + 0.5
            self._poll_configs()
            self._sweep_players()
        if now >= self._next_watch:
            self._next_watch = now + 1.0
            self._watch_files()
        if (Frame, False) in self._handlers:
            self.dispatch(Frame, [])

    def on_map_start(self, map_name: str | None = None) -> None:
        self.amxx.missing.clear()  # Pawn-плагины новой карты могли зарегистрировать нативы
        self._pawn_active = list(self._pawn_written)  # AMXX только что загрузил плагин-приёмник
        if not self._initialized:
            self._initialized = True
            for inst in list(self.instances.values()):
                self.dispatch(Init, [False], only=inst)
        self.dispatch(MapStart, [map_name or self.backend.map_name()])

    def on_map_end(self) -> None:
        self.dispatch(MapEnd, [self.backend.map_name()])

    def _poll_configs(self) -> None:
        for inst in list(self.instances.values()):
            for cfg in inst.configs:
                for attr, listeners in cfg._listeners.items():
                    value = getattr(cfg, attr)
                    old = cfg._seen.get(attr)
                    if value != old:
                        cfg._seen[attr] = value
                        for fn in listeners:
                            self._call(inst, fn, old, value, label=f"on_change({attr})")

    def _watch_files(self) -> None:
        mode = self.backend.cvar_get("amxpy_hotreload")
        if mode is None or mode.strip() != "2":
            return
        for inst in list(self.instances.values()):
            mtime = _mtime(inst.path)
            if mtime is not None and mtime != inst.mtime:
                inst.mtime = mtime
                log.info("%s changed on disk, reloading", inst.path.name if inst.path else inst.name)
                self.reload(inst.name)

"""Импорт плагинов из пакетов: модули видны как ``amxpy.plugins.<плагин>.<модуль>``."""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
from collections.abc import Sequence
from types import CodeType, ModuleType

from .package import ModuleEntry, PluginPackage, load_code

PREFIX = "amxpy.plugins"


def module_name(plugin: str, rel: str = "") -> str:
    return f"{PREFIX}.{plugin}.{rel}" if rel else f"{PREFIX}.{plugin}"


def plugin_modules(plugin: str) -> list[str]:
    root = module_name(plugin)
    return [name for name in sys.modules if name == root or name.startswith(root + ".")]


class PluginImporter(importlib.abc.MetaPathFinder):
    """Находит модули смонтированных пакетов плагинов."""

    def __init__(self) -> None:
        self._packages: dict[str, PluginPackage] = {}

    def mount(self, pkg: PluginPackage) -> None:
        self._packages[pkg.name] = pkg

    def unmount(self, plugin: str) -> None:
        """Убрать пакет и выгрузить его модули из sys.modules."""
        self._packages.pop(plugin, None)
        for name in plugin_modules(plugin):
            del sys.modules[name]
        parent = sys.modules.get(PREFIX)
        if parent is not None and hasattr(parent, plugin):
            delattr(parent, plugin)

    def find_spec(
        self, fullname: str, path: Sequence[str] | None = None, target: ModuleType | None = None
    ) -> importlib.machinery.ModuleSpec | None:
        if not fullname.startswith(PREFIX + "."):
            return None
        plugin, _, rel = fullname[len(PREFIX) + 1 :].partition(".")
        pkg = self._packages.get(plugin)
        entry = pkg.modules.get(rel) if pkg is not None else None
        if entry is None:
            return None
        return importlib.machinery.ModuleSpec(fullname, _Loader(entry), origin=entry.file, is_package=entry.is_package)


class _Loader(importlib.abc.InspectLoader):
    def __init__(self, entry: ModuleEntry) -> None:
        self.entry = entry

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType | None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        exec(self.get_code(module.__name__), module.__dict__)

    def get_code(self, fullname: str) -> CodeType:
        return load_code(self.entry.code, fullname)

    def get_source(self, fullname: str) -> str | None:
        # трейсбеки берут строки отсюда через linecache
        return self.entry.source

    def is_package(self, fullname: str) -> bool:
        return self.entry.is_package

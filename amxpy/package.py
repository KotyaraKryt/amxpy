"""Формат пакета плагина ``.amxpy``.

Zip-архив:
```python
manifest.json        метаданные и декларации — C++-модуль читает их до запуска кода
code/<модуль>.pyc    байткод (стандартный .pyc с хэшем исходника)
src/<модуль>.py      исходники для трейсбеков (в release-сборке нет)
data/...             файлы плагина (переводы и т.п.)
```
"""

from __future__ import annotations

import importlib.util
import io
import json
import marshal
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import CodeType
from typing import Any

FORMAT = 1
API_VERSION = 1
MAGIC = importlib.util.MAGIC_NUMBER
BYTECODE_TAG = sys.implementation.cache_tag  # например, cpython-314


class PackageError(Exception):
    """Пакет повреждён или собран не под этот рантайм."""


@dataclass
class ModuleEntry:
    name: str  # относительное имя: "" — корень пакета, "perks", "detectors.aim"
    file: str  # путь для трейсбеков: "vip/perks.py"
    is_package: bool
    code: bytes  # содержимое .pyc
    source: str | None = None

    @property
    def stem(self) -> str:
        """Путь внутри архива без расширения."""
        base = self.name.replace(".", "/")
        if self.is_package:
            return f"{base}/__init__" if base else "__init__"
        return base


@dataclass
class PluginPackage:
    manifest: dict[str, Any]
    modules: dict[str, ModuleEntry]
    data: dict[str, bytes] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.manifest["name"])

    def check_runtime(self) -> None:
        if self.manifest.get("format") != FORMAT:
            raise PackageError(f"{self.name}: unsupported package format {self.manifest.get('format')!r}")
        runtime = self.manifest.get("runtime", {})
        if runtime.get("magic") != MAGIC.hex():
            raise PackageError(
                f"{self.name}: compiled for {runtime.get('bytecode')}, the server runs {BYTECODE_TAG}; rebuild the plugin"
            )
        if runtime.get("api", 0) > API_VERSION:
            raise PackageError(f"{self.name}: needs amxpy API {runtime.get('api')}, the server has {API_VERSION}")


def make_pyc(code: CodeType, source: bytes) -> bytes:
    flags = 0b01  # .pyc с хэшем исходника; при загрузке хэш не сверяется
    return MAGIC + flags.to_bytes(4, "little") + importlib.util.source_hash(source) + marshal.dumps(code)


def load_code(data: bytes, name: str) -> CodeType:
    if data[:4] != MAGIC:
        raise PackageError(f"{name}: bytecode was compiled by another Python version")
    code = marshal.loads(memoryview(data)[16:])
    if not isinstance(code, CodeType):
        raise PackageError(f"{name}: broken bytecode")
    return code


def write_package(pkg: PluginPackage, path: Path) -> None:
    """Записать пакет атомарно: сервер никогда не увидит наполовину записанный файл."""
    pkg.manifest["modules"] = [
        {"name": e.name, "file": e.file, "package": e.is_package} for e in pkg.modules.values()
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(pkg.manifest, ensure_ascii=False, indent=2))
        for entry in pkg.modules.values():
            zf.writestr(f"code/{entry.stem}.pyc", entry.code)
            if entry.source is not None:
                zf.writestr(f"src/{entry.stem}.py", entry.source)
        for name, blob in pkg.data.items():
            zf.writestr(f"data/{name}", blob)
    tmp.replace(path)


def read_package(source: Path | str | bytes) -> PluginPackage:
    try:
        zf = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackageError(f"{source}: not an amxpy package ({exc})") from exc
    with zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
            names = set(zf.namelist())
            modules: dict[str, ModuleEntry] = {}
            for item in manifest.get("modules", []):
                entry = ModuleEntry(item["name"], item["file"], item["package"], b"")
                entry.code = zf.read(f"code/{entry.stem}.pyc")
                src = f"src/{entry.stem}.py"
                if src in names:
                    entry.source = zf.read(src).decode("utf-8")
                modules[entry.name] = entry
            data = {n[5:]: zf.read(n) for n in names if n.startswith("data/") and not n.endswith("/")}
        except (KeyError, ValueError) as exc:
            raise PackageError(f"{source}: broken package ({exc})") from exc
    return PluginPackage(manifest, modules, data)

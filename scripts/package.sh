#!/usr/bin/env bash
# Дистрибутив для сервера (linux-i386): распаковать в cstrike/ и добавить "amxpy" в configs/modules.ini.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(grep -m1 '^version' "$ROOT/pyproject.toml" | cut -d'"' -f2)"
RUNTIME="$ROOT/build/runtime-i386"
MODULE="$ROOT/build/module/amxpy_amxx_i386.so"
STAGE="$ROOT/dist/server"
ARCHIVE="$ROOT/dist/amxpy-$VERSION-linux-i386.tar.gz"

# только переносимая сборка: хостовая требует glibc машины сборки
[[ -f "$MODULE" && -f "$RUNTIME/lib/libpython3.14.so.1.0" ]] || { echo "сначала scripts/docker-build.sh" >&2; exit 1; }

rm -rf "$STAGE"
mkdir -p "$STAGE/addons/amxmodx/modules" "$STAGE/addons/amxpy/"{plugins,configs,data,python,site-packages,runtime/lib}
strip --strip-unneeded -o "$STAGE/addons/amxmodx/modules/amxpy_amxx_i386.so" "$MODULE"
strip --strip-unneeded -o "$STAGE/addons/amxpy/runtime/lib/libpython3.14.so.1.0" "$RUNTIME/lib/libpython3.14.so.1.0"

# стандартная библиотека без тестов, IDE, Tk и статической libpython
tar -C "$RUNTIME/lib" \
    --exclude='python3.14/test' --exclude='python3.14/idlelib' --exclude='python3.14/tkinter' \
    --exclude='python3.14/turtledemo' --exclude='python3.14/ensurepip' --exclude='python3.14/config-3.14-*' \
    -cf - python3.14 | tar -C "$STAGE/addons/amxpy/runtime/lib" -xf -
tar -C "$ROOT" --exclude='__pycache__' -cf - amxpy | tar -C "$STAGE/addons/amxpy/python" -xf -
printf '; amxpy: plugin packages to load, one per line (addons/amxpy/plugins/)\n' > "$STAGE/addons/amxpy/plugins.ini"

tar -C "$STAGE" -czf "$ARCHIVE" addons
echo "$ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"

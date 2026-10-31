#!/usr/bin/env bash
# Сборка C++-модуля и прогон фейкового HLDS (module/tests/harness.cpp) на настоящих пакетах плагинов.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$ROOT/build/module-host"  # модуль под этот хост — только для харнесса
SERVER="$ROOT/build/harness"
ADDONS="$SERVER/cstrike/addons"
AMXPY_CLI="${AMXPY_CLI:-$ROOT/.venv/bin/amxpy}"

cmake -S "$ROOT/module" -B "$BUILD" -G Ninja -DCMAKE_BUILD_TYPE=Release > /dev/null
cmake --build "$BUILD"

rm -rf "$SERVER"
mkdir -p "$ADDONS/amxmodx/modules" "$ADDONS/amxpy/plugins" "$ADDONS/amxpy/configs" "$ADDONS/amxpy/python"
cp "$BUILD/amxpy_amxx_i386.so" "$ADDONS/amxmodx/modules/"
ln -s "$ROOT/build/runtime-i386" "$ADDONS/amxpy/runtime"
ln -s "$ROOT/amxpy" "$ADDONS/amxpy/python/amxpy"

"$AMXPY_CLI" build "$ROOT/examples/plugins/hello.py" "$ROOT/examples/plugins/vip" "$ROOT/examples/plugins/ui_demo.py" \
    "$ROOT/module/tests/bridge_probe.py" -o "$SERVER/dist" > /dev/null
cp "$SERVER/dist/"*.amxpy "$ADDONS/amxpy/plugins/"
printf 'hello\nvip\nui_demo\nbridge_probe\n' > "$ADDONS/amxpy/plugins.ini"
printf 'hello_delay "0.1"\n' > "$ADDONS/amxpy/configs/hello.cfg"

"$BUILD/amxpy_harness" "$SERVER" "$ADDONS/amxmodx/modules/amxpy_amxx_i386.so"

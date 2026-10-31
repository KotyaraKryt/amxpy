#!/usr/bin/env bash
# Расширение amxpy для VS Code → dist/amxpy-vscode-<версия>.vsix
#   code --install-extension dist/amxpy-vscode-0.1.0.vsix
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXT="$ROOT/editors/vscode"
VERSION="$(node -p "require('$EXT/package.json').version")"
(cd "$EXT" && node --test)
# встроенный индекс нативов для amxx.call: .inc AMX Mod X и ReAPI (scripts/fetch-sdk.sh)
mkdir -p "$EXT/data"
node "$EXT/tools/build-index.js" "$ROOT/module/third_party/amxmodx/plugins/include" \
    "$ROOT/module/third_party/reapi/reapi/extra/amxmodx/scripting/include" > "$EXT/data/natives.json"
mkdir -p "$ROOT/dist"
cp "$ROOT/LICENSE" "$EXT/LICENSE"
trap 'rm -f "$EXT/LICENSE"' EXIT
(cd "$EXT" && npx --yes @vscode/vsce@3.2.1 package \
    -o "$ROOT/dist/amxpy-vscode-$VERSION.vsix")

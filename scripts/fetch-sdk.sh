#!/usr/bin/env bash
# Заголовки для сборки C++-модуля: cssdk (HLSDK + API ReHLDS/ReGameDLL) и Metamod из ReAPI;
# SDK и .inc AMX Mod X (индекс нативов расширения VS Code).
# Ревизии закреплены: обновлять осознанно, проверяя сборку модуля.
set -euo pipefail

REAPI_REPO="https://github.com/rehlds/ReAPI.git"
REAPI_REV="${REAPI_REV:-4516d1efdfd8a686a66c191c441981b720b0a7c5}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/module/third_party/reapi"

if [[ ! -d "$DEST/.git" ]]; then
    git init -q "$DEST"
    git -C "$DEST" remote add origin "$REAPI_REPO"
fi
git -C "$DEST" fetch -q --depth 1 origin "$REAPI_REV"
git -C "$DEST" checkout -q FETCH_HEAD
echo "ReAPI SDK: $(git -C "$DEST" rev-parse HEAD)"

AMXX_REPO="https://github.com/alliedmodders/amxmodx.git"
AMXX_REV="${AMXX_REV:-8fc12670ea86470a0bfed4c35db5de73d3a39e8a}"
AMXX="$ROOT/module/third_party/amxmodx"
if [[ ! -d "$AMXX/.git" ]]; then
    git init -q "$AMXX"
    git -C "$AMXX" remote add origin "$AMXX_REPO"
    git -C "$AMXX" sparse-checkout set public/sdk public/amtl plugins/include
fi
git -C "$AMXX" sparse-checkout add plugins/include
git -C "$AMXX" fetch -q --depth 1 --filter=blob:none origin "$AMXX_REV"
git -C "$AMXX" checkout -q FETCH_HEAD
echo "AMX Mod X SDK + .inc: $(git -C "$AMXX" rev-parse HEAD)"

#!/usr/bin/env bash
# Установить дистрибутив (scripts/package.sh) и плагины в Docker-контейнер с HLDS.
#   scripts/deploy-docker.sh <контейнер> <путь cstrike в контейнере> [плагин.py | папка плагина ...]
# Пример: scripts/deploy-docker.sh cs16-dev /mnt/server/cstrike examples/plugins/hello.py
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="${1:?имя контейнера}"
GAME="${2:?путь к cstrike внутри контейнера}"
shift 2
STAGE="$ROOT/dist/server"
BACKUP="$ROOT/build/deploy-backup/$CONTAINER"
AMXPY_CLI="${AMXPY_CLI:-$ROOT/.venv/bin/amxpy}"

[[ -d "$STAGE/addons" ]] || { echo "сначала scripts/package.sh" >&2; exit 1; }
mkdir -p "$BACKUP"

# плагины: пакеты, plugins.ini и .inc для Pawn
if (($#)); then
    rm -rf "$STAGE/plugins-build"
    "$AMXPY_CLI" build "$@" -o "$STAGE/plugins-build"
    cp "$STAGE/plugins-build/"*.amxpy "$STAGE/addons/amxpy/plugins/"
    for f in "$STAGE/plugins-build/"*.amxpy; do basename "$f" .amxpy; done > "$STAGE/addons/amxpy/plugins.ini"
    if compgen -G "$STAGE/plugins-build/include/*.inc" > /dev/null; then
        mkdir -p "$STAGE/addons/amxmodx/scripting/include"
        cp "$STAGE/plugins-build/include/"*.inc "$STAGE/addons/amxmodx/scripting/include/"
    fi
fi

# modules.ini: дописать amxpy, сохранив исходный файл
MODULES="$GAME/addons/amxmodx/configs/modules.ini"
docker cp "$CONTAINER:$MODULES" "$BACKUP/modules.ini.current"
[[ -f "$BACKUP/modules.ini.orig" ]] || cp "$BACKUP/modules.ini.current" "$BACKUP/modules.ini.orig"
if ! grep -qx "amxpy" "$BACKUP/modules.ini.current"; then
    cp "$BACKUP/modules.ini.current" "$BACKUP/modules.ini.new"
    printf '\namxpy\n' >> "$BACKUP/modules.ini.new"
    docker cp "$BACKUP/modules.ini.new" "$CONTAINER:$MODULES"
fi

docker cp "$STAGE/addons/." "$CONTAINER:$GAME/addons/"
echo "установлено в $CONTAINER:$GAME (исходный modules.ini: $BACKUP/modules.ini.orig)"

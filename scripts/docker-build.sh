#!/usr/bin/env bash
# Переносимая сборка в i386/debian:bullseye (glibc 2.31): бинарники грузятся на Debian 11+,
# Ubuntu 20.04+ и других Linux с glibc >= 2.31, а не только на машине сборки.
#   scripts/docker-build.sh          — рантайм CPython + модуль
#   scripts/docker-build.sh module   — только модуль (рантайм уже собран)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-i386/debian:bullseye}"
OWNER="$(id -u):$(id -g)"
WHAT="${1:-all}"

if [[ "$WHAT" == all ]]; then
    rm -rf "$ROOT/build/runtime-i386"  # build/runtime-src — кэш собранных OpenSSL и SQLite
fi
rm -rf "$ROOT/build/module"

docker run --rm -v "$ROOT:/src" -w /src -e OWNER="$OWNER" -e WHAT="$WHAT" "$IMAGE" linux32 bash -euc '
    trap "chown -R \$OWNER /src/build" EXIT
    # bullseye переехал в архив Debian
    printf "%s\n" "deb http://archive.debian.org/debian bullseye main" \
        "deb http://archive.debian.org/debian-security bullseye-security main" > /etc/apt/sources.list
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends build-essential perl curl ca-certificates xz-utils unzip \
        zlib1g-dev pkg-config cmake ninja-build > /dev/null
    [[ "$WHAT" == module ]] || scripts/build-runtime.sh
    cmake -S module -B build/module -G Ninja -DCMAKE_BUILD_TYPE=Release
    cmake --build build/module
'
for f in build/runtime-i386/lib/libpython3.14.so.1.0 build/module/amxpy_amxx_i386.so; do
    echo "$f: needs $(objdump -T "$ROOT/$f" | grep -oE 'GLIBC_[0-9.]+' | sort -t. -k2 -n -u | tail -1)"
done

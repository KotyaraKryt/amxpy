#!/usr/bin/env bash
# Сборка 32-битного CPython для встраивания в HLDS (linux-i386).
# Результат: build/runtime-i386/{lib/libpython3.14.so*, lib/python3.14/, include/python3.14/}
set -euo pipefail

PY_VERSION="${PY_VERSION:-3.14.4}"
OPENSSL_VERSION="${OPENSSL_VERSION:-3.5.5}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${WORK:-$ROOT/build/runtime-src}"
PREFIX="${PREFIX:-$ROOT/build/runtime-i386}"
JOBS="${JOBS:-$(nproc)}"

mkdir -p "$WORK" "$PREFIX"

# OpenSSL статически внутри _ssl/_hashlib: серверу не нужен libssl:i386 нужной версии
if [[ ! -f "$WORK/openssl/lib/libssl.a" ]]; then
    if ! perl -MIPC::Cmd -e1 2> /dev/null; then
        # в manylinux2014 нет IPC::Cmd; Configure берёт из него только can_run
        mkdir -p "$WORK/perl5/IPC"
        cat > "$WORK/perl5/IPC/Cmd.pm" << 'PERL'
package IPC::Cmd;
use strict;
use File::Spec;
use Exporter 'import';
our @EXPORT_OK = qw(can_run);
our $VERSION = '1.04';
sub can_run {
    my ($cmd) = @_;
    return $cmd if File::Spec->file_name_is_absolute($cmd) && -x $cmd;
    for my $dir (File::Spec->path) {
        my $path = File::Spec->catfile($dir, $cmd);
        return $path if -x $path && !-d $path;
    }
    return undef;
}
1;
PERL
        export PERL5LIB="$WORK/perl5${PERL5LIB:+:$PERL5LIB}"
    fi
    curl -fsSLo "$WORK/openssl.tar.gz" \
        "https://github.com/openssl/openssl/releases/download/openssl-$OPENSSL_VERSION/openssl-$OPENSSL_VERSION.tar.gz"
    rm -rf "$WORK/openssl-src" && mkdir "$WORK/openssl-src"
    tar -C "$WORK/openssl-src" --strip-components=1 -xf "$WORK/openssl.tar.gz"
    (cd "$WORK/openssl-src" \
        && ./Configure linux-elf -m32 -fPIC no-shared no-dso no-tests no-docs --prefix="$WORK/openssl" --libdir=lib \
        && make -j"$JOBS" > /dev/null && make install_sw > /dev/null)
fi

# 32-битного dev-пакета SQLite в системах обычно нет — собираем amalgamation статически.
if [[ ! -f "$WORK/sqlite/libsqlite3.a" ]]; then
    rel=$(curl -fsSL https://www.sqlite.org/download.html \
        | grep -oE 'PRODUCT,[0-9.]+,[0-9]{4}/sqlite-amalgamation-[0-9]+\.zip' | head -1 | cut -d, -f3)
    curl -fsSLo "$WORK/sqlite.zip" "https://www.sqlite.org/$rel"
    rm -rf "$WORK/sqlite" && mkdir "$WORK/sqlite"
    unzip -qj "$WORK/sqlite.zip" -d "$WORK/sqlite"
    gcc -m32 -O2 -fPIC -DSQLITE_THREADSAFE=1 -DSQLITE_OMIT_LOAD_EXTENSION \
        -c "$WORK/sqlite/sqlite3.c" -o "$WORK/sqlite/sqlite3.o"
    ar rcs "$WORK/sqlite/libsqlite3.a" "$WORK/sqlite/sqlite3.o"
fi

if [[ ! -d "$WORK/Python-$PY_VERSION" ]]; then
    curl -fsSLo "$WORK/python.tar.xz" "https://www.python.org/ftp/python/$PY_VERSION/Python-$PY_VERSION.tar.xz"
    tar -C "$WORK" -xf "$WORK/python.tar.xz"
fi

cd "$WORK/Python-$PY_VERSION"
# pkg-config не должен подсовывать 64-битные библиотеки хоста
export PKG_CONFIG_LIBDIR=/usr/lib/i386-linux-gnu/pkgconfig
[[ -d "$PKG_CONFIG_LIBDIR" ]] || export PKG_CONFIG_LIBDIR=/usr/lib/pkgconfig
make distclean > /dev/null 2>&1 || true
./configure \
    CC="gcc -m32" CXX="g++ -m32" \
    LIBSQLITE3_CFLAGS="-I$WORK/sqlite" LIBSQLITE3_LIBS="-L$WORK/sqlite -lsqlite3 -lm" \
    LDFLAGS="-pthread" \
    --prefix="$PREFIX" --enable-shared --without-ensurepip --disable-test-modules \
    --with-openssl="$WORK/openssl" --with-openssl-rpath=no
# -pthread: gcc ставит -lpthread в конец команды, после статического libcrypto (no-dso — без dlopen)
make -j"$JOBS"
make install

echo "runtime: $PREFIX"
LD_LIBRARY_PATH="$PREFIX/lib" "$PREFIX/bin/python3.14" -c \
    "import sys, ssl, sqlite3, zlib, asyncio; print(sys.version, '|', sys.maxsize > 2**32 and '64' or '32', 'bit |', ssl.OPENSSL_VERSION)"

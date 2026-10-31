"""Образ .amxx «моста»: AMX-скрипт без кода, в таблице нативов которого — нужные имена.

Ядро AMXX загружает его как обычный скрипт (LoadAmxScript) и привязывает нативы
модулей, ядра и Pawn-плагинов по имени; C++-модуль читает их адреса и вызывает
нативы, используя кучу этого AMX под строки и массивы.
"""

from __future__ import annotations

import struct
import zlib

AMX_MAGIC = 0xF1E0
AMXX_MAGIC = 0x414D5858
AMXX_VERSION = 0x0300
FILE_VERSION = 8  # CUR_FILE_VERSION AMX Mod X
HEADER = struct.Struct("<iHbbhhiiiiiiiiiii")  # AMX_HEADER, 56 байт
OP_HALT = 120
NAME_MAX = 63  # sNAMEMAX


OP_PROC, OP_PUSH_C, OP_STACK, OP_RETN, OP_SYSREQ_C = 46, 39, 44, 48, 123
FORWARD_NATIVE = "__amxpy_forward"  # натив модуля: зовёт Python-подписчиков форварда


def _image(publics: list[tuple[str, bytes]], natives: list[str], heap_cells: int) -> bytes:
    """AMX-образ: publics — (имя, код функции), natives — имена; код начинается с ``HALT 0``."""
    names = [n for n, _ in publics] + natives
    if not names or len(set(names)) != len(names):
        raise ValueError("names in an AMX image must be unique and non-empty")
    encoded = [n.encode("ascii") for n in names]
    if any(len(n) > NAME_MAX for n in encoded):
        raise ValueError(f"name longer than {NAME_MAX} characters")
    publics_at = HEADER.size
    natives_at = publics_at + 8 * len(publics)
    libraries = natives_at + 8 * len(natives)
    nametable = libraries  # libraries, pubvars и tags пусты
    names_blob = struct.pack("<H", max(len(n) for n in encoded))
    offsets = []
    for name in encoded:
        offsets.append(nametable + len(names_blob))
        names_blob += name + b"\0"
    cod = (nametable + len(names_blob) + 3) & ~3
    code = struct.pack("<ii", OP_HALT, 0)
    addresses = []
    for _, body in publics:
        addresses.append(len(code))
        code += body
    dat = cod + len(code)
    hea = dat + 4  # одна нулевая ячейка данных
    stp = hea + heap_cells * 4
    header = HEADER.pack(
        hea, AMX_MAGIC, FILE_VERSION, FILE_VERSION, 0, 8, cod, dat, hea, stp, 0,
        publics_at, natives_at, libraries, libraries, libraries, nametable,
    )  # fmt: skip
    table = b"".join(struct.pack("<II", a, o) for a, o in zip(addresses, offsets))
    table += b"".join(struct.pack("<II", 0, o) for o in offsets[len(publics) :])
    image = header + table + names_blob
    image += b"\0" * (cod - len(image)) + code + b"\0" * 4
    assert len(image) == hea
    return image


def build_image(names: list[str], heap_cells: int = 16384) -> bytes:
    """Образ моста к нативам: нативы ``names``, publics нет, код — ``HALT 0``."""
    return _image([], names, heap_cells)


def _forward_stub(index: int) -> bytes:
    # public <имя>(...) { return __amxpy_forward(index); } — аргументы натив берёт из кадра
    return struct.pack(
        "<iiiiiiiiii", OP_PROC, OP_PUSH_C, index, OP_PUSH_C, 4, OP_SYSREQ_C, 0, OP_STACK, 8, OP_RETN
    )


def forward_names(names: list[str]) -> list[str]:
    """Порядок publics в плагине-приёмнике: по байтам, как ищет amx_FindPublic."""
    return sorted(set(names), key=lambda n: n.encode("ascii"))


def build_forwards_image(names: list[str], heap_cells: int = 16384) -> bytes:
    """Плагин-приёмник Pawn-форвардов: на каждое имя — public, который зовёт натив модуля."""
    ordered = forward_names(names)
    return _image([(n, _forward_stub(i)) for i, n in enumerate(ordered)], [FORWARD_NATIVE], heap_cells)


def build_amxx(names: list[str], heap_cells: int = 16384, *, image: bytes | None = None) -> bytes:
    """Файл .amxx с одной секцией для 32-битных ячеек: мост к нативам ``names`` или готовый ``image``."""
    image = image if image is not None else build_image(names, heap_cells)
    packed = zlib.compress(image, 9)
    stp = HEADER.unpack_from(image)[9]
    entry = struct.pack("<biiii", 4, len(packed), len(image), stp, 4 + 2 + 1 + 17)
    return struct.pack("<ihb", AMXX_MAGIC, AMXX_VERSION, 1) + entry + packed


def read_amxx(data: bytes) -> tuple[list[tuple[str, int]], list[str]]:
    """(publics: [(имя, адрес кода)], нативы) из .amxx — проверка формата (в тестах и FakeBackend)."""
    magic, version, count = struct.unpack_from("<ihb", data)
    if magic != AMXX_MAGIC or version != AMXX_VERSION or count != 1:
        raise ValueError("not a bridge .amxx")
    cellsize, disksize, imagesize, memsize, offset = struct.unpack_from("<biiii", data, 7)
    if cellsize != 4:
        raise ValueError("bad cell size")
    image = zlib.decompress(data[offset : offset + disksize])
    size, magic, _, _, _, defsize, cod, _, hea, stp, _, _, natives, libraries, *_ = HEADER.unpack_from(image)
    if magic != AMX_MAGIC or defsize != 8 or size != hea or len(image) != imagesize or memsize != stp:
        raise ValueError("bad AMX header")
    if struct.unpack_from("<ii", image, cod) != (OP_HALT, 0):
        raise ValueError("bad bridge code")

    def name(offset: int) -> str:
        return image[offset : image.index(b"\0", offset)].decode("ascii")

    publics = [struct.unpack_from("<II", image, e) for e in range(HEADER.size, natives, defsize)]
    names = [name(struct.unpack_from("<II", image, e)[1]) for e in range(natives, libraries, defsize)]
    return [(name(o), a) for a, o in publics], names


def read_natives(data: bytes) -> list[str]:
    """Имена нативов из .amxx моста."""
    return read_amxx(data)[1]

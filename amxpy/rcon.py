"""RCON GoldSrc (HLDS): команды серверу по UDP — ``amxpy rcon "amxpy list"``."""

from __future__ import annotations

import socket

_HEADER = b"\xff\xff\xff\xff"
TAIL_TIMEOUT = 0.5  # сколько ждать продолжения: длинный вывод приходит несколькими пакетами


class RconError(Exception):
    pass


def rcon(host: str, port: int, password: str, command: str, *, timeout: float = 2.0) -> str:
    """Выполнить команду и вернуть вывод сервера."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.send(_HEADER + b"challenge rcon\n")
        try:
            reply = sock.recv(4096)
        except TimeoutError:
            raise RconError(f"{host}:{port} не отвечает") from None
        parts = reply[4:].split()
        if parts[:2] != [b"challenge", b"rcon"] or len(parts) < 3:
            raise RconError(f"неожиданный ответ на challenge: {reply!r}")
        challenge = parts[2].decode()
        sock.send(_HEADER + f'rcon {challenge} "{password}" {command}\n'.encode())
        output = []
        sock.settimeout(TAIL_TIMEOUT)
        try:
            while True:
                packet = sock.recv(65535)
                text = packet[5:] if packet[4:5] == b"l" else packet[4:]
                output.append(text.decode("utf-8", errors="replace").rstrip("\x00"))
        except TimeoutError:
            pass
    text = "".join(output)
    if text.startswith("Bad rcon_password"):
        raise RconError("неверный rcon_password")
    return text

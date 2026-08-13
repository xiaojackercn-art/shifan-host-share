from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

MAX_FRAME = 2 * 1024 * 1024


def normalize_key(value: str) -> str:
    return "".join(ch for ch in value.upper() if ch.isalnum())


def derive_fernet(mouse_key: str, keyboard_key: str) -> Fernet:
    material = f"SHIFANAI|{normalize_key(mouse_key)}|{normalize_key(keyboard_key)}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = sock.recv(size - len(chunks))
        if not part:
            raise ConnectionError("连接已关闭")
        chunks.extend(part)
    return bytes(chunks)


class SecureChannel:
    def __init__(self, sock: socket.socket, mouse_key: str, keyboard_key: str):
        self.sock = sock
        self.fernet = derive_fernet(mouse_key, keyboard_key)
        self._send_lock = threading.Lock()

    def send(self, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        token = self.fernet.encrypt(raw)
        frame = struct.pack("!I", len(token)) + token
        with self._send_lock:
            self.sock.sendall(frame)

    def recv(self) -> dict[str, Any]:
        header = _recv_exact(self.sock, 4)
        length = struct.unpack("!I", header)[0]
        if length <= 0 or length > MAX_FRAME:
            raise ConnectionError("收到非法数据帧")
        token = _recv_exact(self.sock, length)
        try:
            raw = self.fernet.decrypt(token)
        except InvalidToken as exc:
            raise PermissionError("共享密钥不正确") from exc
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("协议数据格式错误")
        return obj

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

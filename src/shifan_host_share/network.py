from __future__ import annotations

import platform
import socket
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .secure_channel import SecureChannel

StatusCallback = Callable[[str, str], None]
ReleaseCallback = Callable[[], None]


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        sock.close()


@dataclass
class PeerSettings:
    host: str
    port: int
    mouse_key: str
    keyboard_key: str
    direction: str
    mouse_enabled: bool = True
    keyboard_enabled: bool = True


class PeerClient:
    def __init__(self, status_cb: StatusCallback, release_cb: ReleaseCallback):
        self.status_cb = status_cb
        self.release_cb = release_cb
        self.settings: Optional[PeerSettings] = None
        self.channel: Optional[SecureChannel] = None
        self.remote_screen = (1920, 1080)
        self._lock = threading.RLock()
        self._wanted = False
        self._worker: Optional[threading.Thread] = None
        self._reader: Optional[threading.Thread] = None

    @property
    def connected(self) -> bool:
        with self._lock:
            return self.channel is not None

    def start(self, settings: PeerSettings) -> None:
        self.stop()
        self.settings = settings
        self._wanted = True
        self._worker = threading.Thread(target=self._connect_loop, name="peer-connect", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._wanted = False
        with self._lock:
            channel = self.channel
            self.channel = None
        if channel:
            channel.close()
        self.status_cb("idle", "已停止共享")

    def _connect_loop(self) -> None:
        backoff = 1.0
        while self._wanted:
            if self.connected:
                time.sleep(0.5)
                continue
            settings = self.settings
            if not settings:
                return
            self.status_cb("connecting", f"正在连接 {settings.host}:{settings.port} …")
            try:
                sock = socket.create_connection((settings.host, settings.port), timeout=4)
                sock.settimeout(None)
                channel = SecureChannel(sock, settings.mouse_key, settings.keyboard_key)
                channel.send({
                    "type": "hello",
                    "device": socket.gethostname(),
                    "os": platform.system(),
                    "direction": settings.direction,
                    "mouse_enabled": settings.mouse_enabled,
                    "keyboard_enabled": settings.keyboard_enabled,
                })
                reply = channel.recv()
                if reply.get("type") != "hello_ok":
                    raise ConnectionError(reply.get("message", "对端拒绝连接"))
                screen = reply.get("screen", [1920, 1080])
                self.remote_screen = (int(screen[0]), int(screen[1]))
                with self._lock:
                    self.channel = channel
                self.status_cb("connected", f"已连接：{reply.get('device', settings.host)}")
                backoff = 1.0
                self._reader = threading.Thread(target=self._read_loop, args=(channel,), name="peer-reader", daemon=True)
                self._reader.start()
            except PermissionError:
                self.status_cb("error", "密钥不匹配，请检查第二台电脑显示的鼠标/键盘密钥")
                time.sleep(3)
            except Exception as exc:
                self.status_cb("error", f"连接失败：{exc}")
                time.sleep(backoff)
                backoff = min(5.0, backoff + 1.0)

    def _read_loop(self, channel: SecureChannel) -> None:
        try:
            while self._wanted:
                msg = channel.recv()
                kind = msg.get("type")
                if kind == "release":
                    self.release_cb()
                elif kind == "pong":
                    pass
        except Exception:
            pass
        finally:
            with self._lock:
                if self.channel is channel:
                    self.channel = None
            channel.close()
            if self._wanted:
                self.status_cb("error", "连接断开，正在自动重连…")

    def send(self, payload: dict) -> bool:
        with self._lock:
            channel = self.channel
        if not channel:
            return False
        try:
            channel.send(payload)
            return True
        except Exception:
            with self._lock:
                if self.channel is channel:
                    self.channel = None
            channel.close()
            self.status_cb("error", "连接中断，正在自动重连…")
            return False

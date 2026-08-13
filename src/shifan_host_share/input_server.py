from __future__ import annotations

import socket
import threading
from typing import Callable

from pynput import keyboard, mouse

from .secure_channel import SecureChannel

StatusCallback = Callable[[str, str], None]


class InputServer:
    def __init__(self, port: int, mouse_key: str, keyboard_key: str, screen_size: tuple[int, int], status_cb: StatusCallback):
        self.port = port
        self.mouse_key = mouse_key
        self.keyboard_key = keyboard_key
        self.screen_size = screen_size
        self.status_cb = status_cb
        self._server: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.mouse_ctl = mouse.Controller()
        self.keyboard_ctl = keyboard.Controller()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="input-server", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        self._server = None

    def _serve(self) -> None:
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", self.port))
            srv.listen(8)
            srv.settimeout(1.0)
            self._server = srv
            self.status_cb("server", f"本机接收服务已启动，端口 {self.port}")
            while not self._stop.is_set():
                try:
                    client, addr = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                threading.Thread(target=self._handle_client, args=(client, addr), daemon=True).start()
        except Exception as exc:
            self.status_cb("server_error", f"本机接收服务启动失败：{exc}")

    def _handle_client(self, sock: socket.socket, addr) -> None:
        channel = SecureChannel(sock, self.mouse_key, self.keyboard_key)
        direction = "right"
        mouse_enabled = True
        keyboard_enabled = True
        try:
            hello = channel.recv()
            if hello.get("type") != "hello":
                raise ConnectionError("握手数据无效")
            direction = str(hello.get("direction", "right"))
            mouse_enabled = bool(hello.get("mouse_enabled", True))
            keyboard_enabled = bool(hello.get("keyboard_enabled", True))
            channel.send({
                "type": "hello_ok",
                "device": socket.gethostname(),
                "screen": list(self.screen_size),
            })
            self.status_cb("incoming", f"已接受来自 {hello.get('device', addr[0])} 的共享连接")
            while not self._stop.is_set():
                msg = channel.recv()
                kind = msg.get("type")
                if kind == "activate" and mouse_enabled:
                    self._activate_cursor(direction, float(msg.get("ratio", 0.5)))
                elif kind == "move_rel" and mouse_enabled:
                    self._move_relative(channel, direction, int(msg.get("dx", 0)), int(msg.get("dy", 0)))
                elif kind == "mouse_button" and mouse_enabled:
                    self._mouse_button(str(msg.get("button", "left")), bool(msg.get("pressed", True)))
                elif kind == "scroll" and mouse_enabled:
                    self.mouse_ctl.scroll(int(msg.get("dx", 0)), int(msg.get("dy", 0)))
                elif kind == "key" and keyboard_enabled:
                    self._keyboard_event(msg)
                elif kind == "ping":
                    channel.send({"type": "pong"})
        except PermissionError:
            self.status_cb("incoming_error", f"拒绝 {addr[0]}：共享密钥错误")
        except Exception:
            pass
        finally:
            channel.close()

    def _activate_cursor(self, direction: str, ratio: float) -> None:
        width, height = self.screen_size
        ratio = min(1.0, max(0.0, ratio))
        if direction == "right":
            pos = (3, int(ratio * max(1, height - 1)))
        elif direction == "left":
            pos = (max(0, width - 4), int(ratio * max(1, height - 1)))
        elif direction == "down":
            pos = (int(ratio * max(1, width - 1)), 3)
        else:
            pos = (int(ratio * max(1, width - 1)), max(0, height - 4))
        self.mouse_ctl.position = pos

    def _move_relative(self, channel: SecureChannel, direction: str, dx: int, dy: int) -> None:
        width, height = self.screen_size
        x, y = self.mouse_ctl.position
        nx = max(0, min(width - 1, int(x + dx)))
        ny = max(0, min(height - 1, int(y + dy)))
        self.mouse_ctl.position = (nx, ny)

        release = False
        if direction == "right" and nx <= 0 and dx < 0:
            release = True
        elif direction == "left" and nx >= width - 1 and dx > 0:
            release = True
        elif direction == "down" and ny <= 0 and dy < 0:
            release = True
        elif direction == "up" and ny >= height - 1 and dy > 0:
            release = True
        if release:
            channel.send({"type": "release"})

    def _mouse_button(self, name: str, pressed: bool) -> None:
        button = getattr(mouse.Button, name, mouse.Button.left)
        if pressed:
            self.mouse_ctl.press(button)
        else:
            self.mouse_ctl.release(button)

    def _keyboard_event(self, msg: dict) -> None:
        key_type = msg.get("key_type")
        pressed = bool(msg.get("pressed", True))
        if key_type == "special":
            key = getattr(keyboard.Key, str(msg.get("name", "")), None)
            if key is None:
                return
        else:
            char = msg.get("char")
            vk = msg.get("vk")
            if char:
                key = keyboard.KeyCode.from_char(str(char))
            elif vk is not None:
                key = keyboard.KeyCode.from_vk(int(vk))
            else:
                return
        if pressed:
            self.keyboard_ctl.press(key)
        else:
            self.keyboard_ctl.release(key)

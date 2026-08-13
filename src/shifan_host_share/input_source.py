from __future__ import annotations

import ctypes
import platform
import queue
import time
import tkinter as tk
from typing import Callable

from pynput import keyboard, mouse

from .network import PeerClient


def configure_windows_dpi() -> None:
    if platform.system() != "Windows":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class InputSource:
    def __init__(self, root: tk.Tk, client: PeerClient, screen_size: tuple[int, int], direction_getter: Callable[[], str], mouse_enabled_getter: Callable[[], bool], keyboard_enabled_getter: Callable[[], bool], status_cb: Callable[[str], None]):
        self.root = root
        self.client = client
        self.screen_size = screen_size
        self.direction_getter = direction_getter
        self.mouse_enabled_getter = mouse_enabled_getter
        self.keyboard_enabled_getter = keyboard_enabled_getter
        self.status_cb = status_cb
        self.mouse_ctl = mouse.Controller()
        self.remote_active = False
        self.sharing_enabled = False
        self._ui_queue: queue.Queue[str] = queue.Queue()
        self._warping = False
        self._last_warp = 0.0
        self._activation_cooldown = 0.0
        self._overlay = self._create_overlay()
        self._mouse_listener = mouse.Listener(on_move=self._on_global_move)
        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self._mouse_listener.daemon = True
        self._keyboard_listener.daemon = True
        self._mouse_listener.start()
        self._keyboard_listener.start()
        self.root.after(20, self._drain_ui_queue)

    def _create_overlay(self) -> tk.Toplevel:
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.015)
        except tk.TclError:
            pass
        win.configure(bg="black", cursor="none")
        win.bind("<Motion>", self._on_overlay_motion)
        win.bind("<ButtonPress-1>", lambda e: self._send_button("left", True))
        win.bind("<ButtonRelease-1>", lambda e: self._send_button("left", False))
        win.bind("<ButtonPress-2>", lambda e: self._send_button("middle", True))
        win.bind("<ButtonRelease-2>", lambda e: self._send_button("middle", False))
        win.bind("<ButtonPress-3>", lambda e: self._send_button("right", True))
        win.bind("<ButtonRelease-3>", lambda e: self._send_button("right", False))
        win.bind("<MouseWheel>", self._on_mousewheel)
        win.bind("<Button-4>", lambda e: self._send_scroll(0, 1))
        win.bind("<Button-5>", lambda e: self._send_scroll(0, -1))
        return win

    def enable(self) -> None:
        self.sharing_enabled = True
        self._activation_cooldown = time.monotonic() + 0.8

    def disable(self) -> None:
        self.sharing_enabled = False
        self._ui_queue.put("release")

    def request_release(self) -> None:
        self._ui_queue.put("release")

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                action = self._ui_queue.get_nowait()
                if action == "activate":
                    self._activate_remote_ui()
                elif action == "release":
                    self._release_remote_ui()
        except queue.Empty:
            pass
        self.root.after(20, self._drain_ui_queue)

    def _on_global_move(self, x, y, injected=False):
        if injected or self.remote_active or not self.sharing_enabled:
            return
        if not self.mouse_enabled_getter() or not self.client.connected:
            return
        if time.monotonic() < self._activation_cooldown:
            return
        width, height = self.screen_size
        direction = self.direction_getter()
        threshold = 2
        hit = ((direction == "right" and x >= width - threshold) or (direction == "left" and x <= threshold) or (direction == "down" and y >= height - threshold) or (direction == "up" and y <= threshold))
        if not hit:
            return
        ratio = (y / max(1, height - 1)) if direction in ("right", "left") else (x / max(1, width - 1))
        if self.client.send({"type": "activate", "ratio": max(0.0, min(1.0, ratio))}):
            self.remote_active = True
            self._ui_queue.put("activate")

    def _activate_remote_ui(self) -> None:
        width, height = self.screen_size
        self._overlay.geometry(f"{width}x{height}+0+0")
        self._overlay.deiconify()
        self._overlay.lift()
        try:
            self._overlay.focus_force()
        except tk.TclError:
            pass
        self._warp_center()
        self.status_cb("鼠标/键盘当前正在控制第二台电脑；把鼠标从第二台电脑靠近返回边缘即可回来。")

    def _release_remote_ui(self) -> None:
        if not self.remote_active:
            try:
                self._overlay.withdraw()
            except tk.TclError:
                pass
            return
        self.remote_active = False
        try:
            self._overlay.withdraw()
        except tk.TclError:
            pass
        width, height = self.screen_size
        direction = self.direction_getter()
        x, y = self.mouse_ctl.position
        if direction == "right":
            pos = (max(0, width - 5), min(height - 1, int(y)))
        elif direction == "left":
            pos = (4, min(height - 1, int(y)))
        elif direction == "down":
            pos = (min(width - 1, int(x)), max(0, height - 5))
        else:
            pos = (min(width - 1, int(x)), 4)
        try:
            self.mouse_ctl.position = pos
        except Exception:
            pass
        self._activation_cooldown = time.monotonic() + 0.8
        self.status_cb("已回到本机。")

    def _warp_center(self) -> None:
        width, height = self.screen_size
        self._warping = True
        self._last_warp = time.monotonic()
        try:
            self.mouse_ctl.position = (width // 2, height // 2)
        finally:
            self.root.after(12, self._clear_warp)

    def _clear_warp(self) -> None:
        self._warping = False

    def _on_overlay_motion(self, event) -> None:
        if not self.remote_active or self._warping:
            return
        if time.monotonic() - self._last_warp < 0.01:
            return
        width, height = self.screen_size
        cx, cy = width // 2, height // 2
        dx = int(event.x_root - cx)
        dy = int(event.y_root - cy)
        if dx == 0 and dy == 0:
            return
        dx = max(-180, min(180, dx))
        dy = max(-180, min(180, dy))
        self.client.send({"type": "move_rel", "dx": dx, "dy": dy})
        self._warp_center()

    def _send_button(self, button: str, pressed: bool) -> None:
        if self.remote_active and self.mouse_enabled_getter():
            self.client.send({"type": "mouse_button", "button": button, "pressed": pressed})

    def _on_mousewheel(self, event) -> None:
        delta = int(event.delta)
        if platform.system() == "Darwin":
            steps = 1 if delta > 0 else -1
        else:
            steps = int(delta / 120) if abs(delta) >= 120 else (1 if delta > 0 else -1)
        self._send_scroll(0, steps)

    def _send_scroll(self, dx: int, dy: int) -> None:
        if self.remote_active and self.mouse_enabled_getter():
            self.client.send({"type": "scroll", "dx": dx, "dy": dy})

    def _serialize_key(self, key) -> dict | None:
        if isinstance(key, keyboard.Key):
            return {"key_type": "special", "name": key.name}
        if isinstance(key, keyboard.KeyCode):
            if key.char is not None:
                return {"key_type": "char", "char": key.char}
            if key.vk is not None:
                return {"key_type": "vk", "vk": int(key.vk)}
        return None

    def _on_key_press(self, key, injected=False):
        if injected or not self.remote_active or not self.keyboard_enabled_getter():
            return
        payload = self._serialize_key(key)
        if payload:
            payload.update({"type": "key", "pressed": True})
            self.client.send(payload)

    def _on_key_release(self, key, injected=False):
        if injected or not self.remote_active or not self.keyboard_enabled_getter():
            return
        payload = self._serialize_key(key)
        if payload:
            payload.update({"type": "key", "pressed": False})
            self.client.send(payload)

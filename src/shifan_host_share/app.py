from __future__ import annotations

import platform
import socket
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from .config import load_config, regenerate_local_keys, save_config
from .input_server import InputServer
from .input_source import InputSource, configure_windows_dpi
from .network import PeerClient, PeerSettings, local_ip

APP_NAME = "视饭AI:主机共享"


class App:
    def __init__(self):
        configure_windows_dpi()
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("760x720")
        self.root.minsize(700, 660)
        self.root.configure(bg="#F5F7FB")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.screen_size = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())

        self.status_var = tk.StringVar(value="准备就绪")
        self.incoming_var = tk.StringVar(value="本机接收服务正在启动…")
        self.mouse_enabled_var = tk.BooleanVar(value=bool(self.cfg["peer"].get("mouse_enabled", True)))
        self.keyboard_enabled_var = tk.BooleanVar(value=bool(self.cfg["peer"].get("keyboard_enabled", True)))
        self.direction_var = tk.StringVar(value=self.cfg["peer"].get("direction", "right"))

        self.client = PeerClient(self._peer_status_from_thread, self._release_from_thread)
        self.source = InputSource(self.root, self.client, self.screen_size, lambda: self.direction_var.get(), lambda: self.mouse_enabled_var.get(), lambda: self.keyboard_enabled_var.get(), self._set_hint)
        self.server: InputServer | None = None
        self._build_ui()
        self._start_server()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=(10, 7))
        style.configure("TCheckbutton", background="#FFFFFF", font=("Microsoft YaHei UI", 10))
        style.configure("TLabel", background="#FFFFFF", font=("Microsoft YaHei UI", 10))

        header = tk.Frame(self.root, bg="#111827", height=88)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=APP_NAME, fg="white", bg="#111827", font=("Microsoft YaHei UI", 21, "bold")).pack(anchor="w", padx=26, pady=(17, 1))
        tk.Label(header, text="一套鼠标键盘，直接跨到另一台 Windows / macOS 电脑", fg="#C7D2FE", bg="#111827", font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=27)

        body = tk.Frame(self.root, bg="#F5F7FB")
        body.pack(fill="both", expand=True, padx=20, pady=16)

        local_card = self._card(body, "① 第二台电脑：把这里的连接信息告诉主控电脑")
        local_card.pack(fill="x", pady=(0, 12))
        info_grid = tk.Frame(local_card, bg="white")
        info_grid.pack(fill="x", padx=18, pady=(0, 14))
        self._info_row(info_grid, 0, "本机名称", socket.gethostname())
        self._info_row(info_grid, 1, "本机 IP", local_ip())
        self._info_row(info_grid, 2, "端口", str(self.cfg["port"]))
        self._info_row(info_grid, 3, "鼠标密钥", self.cfg["mouse_key"], copy=True)
        self._info_row(info_grid, 4, "键盘密钥", self.cfg["keyboard_key"], copy=True)

        action_bar = tk.Frame(local_card, bg="white")
        action_bar.pack(fill="x", padx=18, pady=(0, 14))
        ttk.Button(action_bar, text="重新生成本机密钥", command=self._regenerate_keys).pack(side="left")
        if platform.system() == "Windows":
            ttk.Button(action_bar, text="修复 Windows 防火墙", command=self._fix_firewall).pack(side="left", padx=8)
        tk.Label(action_bar, textvariable=self.incoming_var, bg="white", fg="#4B5563", font=("Microsoft YaHei UI", 9)).pack(side="right")

        peer_card = self._card(body, "② 主控电脑：填写第二台电脑的信息")
        peer_card.pack(fill="x", pady=(0, 12))
        form = tk.Frame(peer_card, bg="white")
        form.pack(fill="x", padx=18, pady=(0, 12))

        peer = self.cfg["peer"]
        self.host_var = tk.StringVar(value=peer.get("host", ""))
        self.port_var = tk.StringVar(value=str(peer.get("port", self.cfg["port"])))
        self.peer_mouse_key_var = tk.StringVar(value=peer.get("mouse_key", ""))
        self.peer_keyboard_key_var = tk.StringVar(value=peer.get("keyboard_key", ""))
        self._entry_row(form, 0, "第二台电脑 IP", self.host_var, "例如 192.168.1.23")
        self._entry_row(form, 1, "端口", self.port_var, str(self.cfg["port"]))
        self._entry_row(form, 2, "第二台鼠标密钥", self.peer_mouse_key_var, "从第二台电脑复制")
        self._entry_row(form, 3, "第二台键盘密钥", self.peer_keyboard_key_var, "从第二台电脑复制")

        row = tk.Frame(form, bg="white")
        row.grid(row=4, column=0, columnspan=3, sticky="ew", pady=6)
        tk.Label(row, text="第二台屏幕位置", width=16, anchor="w", bg="white", font=("Microsoft YaHei UI", 10)).pack(side="left")
        for text, value in [("右侧", "right"), ("左侧", "left"), ("下方", "down"), ("上方", "up")]:
            ttk.Radiobutton(row, text=text, value=value, variable=self.direction_var).pack(side="left", padx=(0, 12))

        toggles = tk.Frame(form, bg="white")
        toggles.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4, 2))
        ttk.Checkbutton(toggles, text="鼠标共享", variable=self.mouse_enabled_var).pack(side="left", padx=(128, 18))
        ttk.Checkbutton(toggles, text="键盘共享", variable=self.keyboard_enabled_var).pack(side="left")

        buttons = tk.Frame(peer_card, bg="white")
        buttons.pack(fill="x", padx=18, pady=(2, 16))
        tk.Button(buttons, text="保存并启动共享", command=self._start_share, bg="#2563EB", fg="white", activebackground="#1D4ED8", activeforeground="white", relief="flat", font=("Microsoft YaHei UI", 11, "bold"), padx=22, pady=9, cursor="hand2").pack(side="left")
        ttk.Button(buttons, text="停止共享", command=self._stop_share).pack(side="left", padx=10)
        tk.Label(buttons, textvariable=self.status_var, bg="white", fg="#2563EB", font=("Microsoft YaHei UI", 9, "bold")).pack(side="right")

        hint = self._card(body, "使用方式")
        hint.pack(fill="x")
        self.hint_var = tk.StringVar(value="两台电脑都打开本软件。主控电脑连接成功后，把鼠标推到设置的屏幕边缘，就会自动进入第二台电脑；键盘会跟随鼠标。")
        tk.Label(hint, textvariable=self.hint_var, justify="left", wraplength=670, bg="white", fg="#4B5563", font=("Microsoft YaHei UI", 10), padx=18, pady=4).pack(fill="x", pady=(0, 14))
        if platform.system() == "Darwin":
            tk.Label(hint, text="macOS 首次使用必须在 系统设置 → 隐私与安全性 → 辅助功能 / 输入监控 中允许本软件。", justify="left", wraplength=670, bg="white", fg="#B45309", font=("Microsoft YaHei UI", 9, "bold"), padx=18, pady=(0, 12)).pack(fill="x")

    def _card(self, parent, title: str) -> tk.Frame:
        card = tk.Frame(parent, bg="white", highlightbackground="#E5E7EB", highlightthickness=1)
        tk.Label(card, text=title, bg="white", fg="#111827", font=("Microsoft YaHei UI", 11, "bold"), anchor="w").pack(fill="x", padx=18, pady=(14, 10))
        return card

    def _info_row(self, parent, row: int, label: str, value: str, copy: bool = False) -> None:
        tk.Label(parent, text=label, width=16, anchor="w", bg="white", fg="#374151", font=("Microsoft YaHei UI", 10)).grid(row=row, column=0, sticky="w", pady=5)
        tk.Label(parent, text=value, anchor="w", bg="#F9FAFB", fg="#111827", font=("Consolas", 10), padx=8, pady=5).grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=3)
        if copy:
            ttk.Button(parent, text="复制", command=lambda v=value: self._copy(v)).grid(row=row, column=2, pady=3)
        parent.columnconfigure(1, weight=1)

    def _entry_row(self, parent, row: int, label: str, variable: tk.StringVar, placeholder: str) -> None:
        tk.Label(parent, text=label, width=16, anchor="w", bg="white", fg="#374151", font=("Microsoft YaHei UI", 10)).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=variable, font=("Microsoft YaHei UI", 10)).grid(row=row, column=1, sticky="ew", pady=6)
        tk.Label(parent, text=placeholder, bg="white", fg="#9CA3AF", font=("Microsoft YaHei UI", 9)).grid(row=row, column=2, sticky="w", padx=8)
        parent.columnconfigure(1, weight=1)

    def _copy(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.status_var.set("已复制")

    def _start_server(self) -> None:
        if self.server:
            self.server.stop()
        self.server = InputServer(int(self.cfg["port"]), self.cfg["mouse_key"], self.cfg["keyboard_key"], self.screen_size, self._server_status_from_thread)
        self.server.start()

    def _regenerate_keys(self) -> None:
        if not messagebox.askyesno("重新生成密钥", "重新生成后，之前保存过本机密钥的电脑需要重新填写。继续吗？"):
            return
        regenerate_local_keys(self.cfg)
        messagebox.showinfo("已生成", "本机鼠标密钥和键盘密钥已更新。软件将重新启动以应用新密钥。")
        self._restart_app()

    def _fix_firewall(self) -> None:
        if platform.system() != "Windows":
            return
        port = int(self.cfg["port"])
        args = f'advfirewall firewall add rule name="视饭AI主机共享" dir=in action=allow protocol=TCP localport={port}'
        try:
            if ctypes_shell_execute_runas("netsh.exe", args):
                self.status_var.set("已请求管理员权限添加防火墙规则")
        except Exception as exc:
            messagebox.showerror("防火墙", f"无法添加规则：{exc}")

    def _start_share(self) -> None:
        host = self.host_var.get().strip()
        if not host:
            messagebox.showwarning("缺少 IP", "请输入第二台电脑界面上显示的本机 IP。")
            return
        try:
            port = int(self.port_var.get().strip())
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showwarning("端口错误", "端口请输入 1-65535 的数字。")
            return
        mouse_key = self.peer_mouse_key_var.get().strip()
        keyboard_key = self.peer_keyboard_key_var.get().strip()
        if not mouse_key or not keyboard_key:
            messagebox.showwarning("缺少密钥", "请把第二台电脑显示的鼠标密钥、键盘密钥都填写完整。")
            return
        peer = {"host": host, "port": port, "mouse_key": mouse_key, "keyboard_key": keyboard_key, "direction": self.direction_var.get(), "mouse_enabled": self.mouse_enabled_var.get(), "keyboard_enabled": self.keyboard_enabled_var.get()}
        self.cfg["peer"] = peer
        save_config(self.cfg)
        self.client.start(PeerSettings(**peer))
        self.source.enable()
        self.status_var.set("正在连接…")
        self.hint_var.set("连接成功后，把鼠标一直推向第二台屏幕所在方向即可跨屏。断线会自动重连。")

    def _stop_share(self) -> None:
        self.source.disable()
        self.client.stop()
        self.status_var.set("已停止")

    def _peer_status_from_thread(self, kind: str, text: str) -> None:
        self.root.after(0, lambda: self._set_peer_status(kind, text))

    def _set_peer_status(self, kind: str, text: str) -> None:
        self.status_var.set(text)
        if kind == "connected":
            self.source.enable()
            self.hint_var.set("已连接。现在把鼠标推向第二台屏幕所在边缘；鼠标进入第二台后，键盘也会自动跟随。")

    def _server_status_from_thread(self, kind: str, text: str) -> None:
        self.root.after(0, lambda: self.incoming_var.set(text))

    def _release_from_thread(self) -> None:
        self.source.request_release()

    def _set_hint(self, text: str) -> None:
        self.hint_var.set(text)

    def _restart_app(self) -> None:
        self._shutdown()
        try:
            subprocess.Popen([sys.executable] + sys.argv[1:])
        finally:
            self.root.destroy()

    def _shutdown(self) -> None:
        self.source.disable()
        self.client.stop()
        if self.server:
            self.server.stop()

    def _on_close(self) -> None:
        self._shutdown()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def ctypes_shell_execute_runas(program: str, params: str) -> bool:
    import ctypes
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", program, params, None, 1)
    return result > 32

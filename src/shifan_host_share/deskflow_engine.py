from __future__ import annotations

import configparser
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from .config import app_data_dir

DESKFLOW_VERSION = "1.26.0"


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        if platform.system() == "Darwin":
            return Path(sys.executable).resolve().parents[1] / "Resources"
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def core_path() -> Path:
    root = resource_root()
    if platform.system() == "Windows":
        candidates = [root / "engine" / "Deskflow" / "deskflow-core.exe", root / "engine" / "deskflow-core.exe"]
    elif platform.system() == "Darwin":
        candidates = [
            root / "engine" / "Deskflow.app" / "Contents" / "MacOS" / "deskflow-core",
            root / "engine" / "Deskflow" / "Deskflow.app" / "Contents" / "MacOS" / "deskflow-core",
        ]
    else:
        candidates = [root / "engine" / "deskflow-core", Path("/usr/bin/deskflow-core")]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def safe_screen_name(prefix: str, device_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]", "", device_id)[:12] or "DEVICE"
    return f"{prefix}-{clean}"


def reverse_direction(direction: str) -> str:
    return {"right": "left", "left": "right", "up": "down", "down": "up"}.get(direction, "left")


def build_server_config(server_name: str, client_name: str, direction: str) -> str:
    if direction not in {"right", "left", "up", "down"}:
        raise ValueError("屏幕方向无效")
    opposite = reverse_direction(direction)
    return (
        "section: screens\n"
        f"    {server_name}:\n"
        f"    {client_name}:\n"
        "end\n\n"
        "section: links\n"
        f"    {server_name}:\n"
        f"        {direction} = {client_name}\n"
        f"    {client_name}:\n"
        f"        {opposite} = {server_name}\n"
        "end\n\n"
        "section: options\n"
        "    heartbeat = 3000\n"
        "    switchDelay = 0\n"
        "end\n"
    )


def _write_settings(
    path: Path,
    *,
    computer_name: str,
    port: int,
    remote_host: str = "",
    server_config: Path | None = None,
    interface: str = "",
) -> None:
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str
    core = {
        "computerName": computer_name,
        "port": str(int(port)),
        "processMode": "1",  # Desktop mode; official Deskflow workaround avoids the Windows daemon path.
        "useHooks": "true",
    }
    if interface:
        core["interface"] = interface
    cfg["core"] = core
    cfg["security"] = {"tlsEnabled": "false", "checkPeerFingerprints": "false"}
    cfg["log"] = {"level": "4", "toFile": "false"}
    if remote_host:
        cfg["client"] = {"remoteHost": remote_host, "languageSync": "true"}
    if server_config is not None:
        cfg["server"] = {"externalConfig": "true", "externalConfigFile": str(server_config)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        cfg.write(fh, space_around_delimiters=False)


class DeskflowEngine:
    def __init__(self, status_cb: Callable[[str, str], None] | None = None):
        self.status_cb = status_cb or (lambda _kind, _text: None)
        self.server_process: subprocess.Popen | None = None
        self.client_process: subprocess.Popen | None = None
        self._lock = threading.RLock()
        self._server_connected = False
        self._client_connected = False
        self._server_log: list[str] = []
        self._client_log: list[str] = []

    def available(self) -> tuple[bool, str]:
        path = core_path()
        return path.exists(), str(path)

    def stop_all(self) -> None:
        self.stop_server()
        self.stop_client()

    def _terminate(self, proc: subprocess.Popen | None) -> None:
        if not proc or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def stop_server(self) -> None:
        with self._lock:
            proc = self.server_process
            self.server_process = None
            self._server_connected = False
        self._terminate(proc)

    def stop_client(self) -> None:
        with self._lock:
            proc = self.client_process
            self.client_process = None
            self._client_connected = False
        self._terminate(proc)

    def start_server(self, server_name: str, client_name: str, direction: str, port: int, listen_ip: str = "") -> tuple[bool, str]:
        self.stop_all()
        path = core_path()
        if not path.exists():
            return False, f"Deskflow 核心缺失：{path}"
        runtime = app_data_dir() / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        server_config = runtime / "deskflow-server.conf"
        settings = runtime / "deskflow-server-settings.ini"
        server_config.write_text(build_server_config(server_name, client_name, direction), "utf-8")
        _write_settings(settings, computer_name=server_name, port=port, server_config=server_config, interface=listen_ip)
        ok, message, proc = self._spawn([str(path), "server", "--settings", str(settings)], "server")
        if ok:
            with self._lock:
                self.server_process = proc
                self._server_connected = False
            return True, f"Deskflow 主控已监听 {listen_ip or '全部网卡'}:{port}"
        return False, message

    def start_client(self, server_ip: str, server_port: int, client_name: str) -> tuple[bool, str]:
        self.stop_all()
        path = core_path()
        if not path.exists():
            return False, f"Deskflow 核心缺失：{path}"
        runtime = app_data_dir() / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        settings = runtime / "deskflow-client-settings.ini"
        _write_settings(settings, computer_name=client_name, port=server_port, remote_host=server_ip)
        ok, message, proc = self._spawn([str(path), "client", "--settings", str(settings)], "client")
        if ok:
            with self._lock:
                self.client_process = proc
                self._client_connected = False
            return True, f"Deskflow 第二台电脑正在主动连接 {server_ip}:{server_port}"
        return False, message

    def _spawn(self, command: list[str], role: str) -> tuple[bool, str, subprocess.Popen | None]:
        kwargs: dict = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if platform.system() == "Windows":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(command, **kwargs)
        except Exception as exc:
            return False, f"无法启动 Deskflow：{exc}", None
        threading.Thread(target=self._read_output, args=(proc, role), name=f"deskflow-{role}-log", daemon=True).start()
        time.sleep(1.0)
        if proc.poll() is not None:
            log = self.recent_log(role, 12)
            return False, f"Deskflow 启动失败（退出码 {proc.returncode}）{': ' + log if log else ''}", None
        return True, "ok", proc

    def _read_output(self, proc: subprocess.Popen, role: str) -> None:
        if not proc.stdout:
            return
        for raw in proc.stdout:
            line = raw.strip()
            if not line:
                continue
            with self._lock:
                target = self._server_log if role == "server" else self._client_log
                target.append(line)
                del target[:-120]
            low = line.lower()
            if role == "server" and ("has connected" in low or "accepted client connection" in low):
                with self._lock:
                    self._server_connected = True
                self.status_cb("connected", "连接成功 · 鼠标可以跨屏，键盘会自动跟随")
            elif role == "client" and ("connected to server" in low or "connected to secure socket" in low):
                with self._lock:
                    self._client_connected = True
                self.status_cb("remote_connected", "已连接主控电脑 · 正在接受键鼠控制")
            elif "failed to connect" in low or "fatal" in low or "error:" in low or "critical" in low:
                self.status_cb("engine_log", line)

    def recent_log(self, role: str, count: int = 12) -> str:
        with self._lock:
            items = self._server_log if role == "server" else self._client_log
            return " | ".join(items[-count:])

    def status(self) -> dict:
        with self._lock:
            return {
                "server_alive": bool(self.server_process and self.server_process.poll() is None),
                "client_alive": bool(self.client_process and self.client_process.poll() is None),
                "server_connected": self._server_connected,
                "client_connected": self._client_connected,
                "server_log": self._server_log[-4:],
                "client_log": self._client_log[-4:],
            }

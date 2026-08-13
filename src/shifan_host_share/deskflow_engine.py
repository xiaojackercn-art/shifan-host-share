from __future__ import annotations

import configparser
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePath
from typing import Callable

from .config import app_data_dir
from .lan_bridge import TcpForwarder, probe_tcp

DESKFLOW_VERSION = "1.26.0"
DEFAULT_PORT = 24800
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 24810


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


def _qsettings_path(path: PurePath) -> str:
    """Serialize paths in the form Qt/QSettings preserves on Windows."""
    return path.as_posix()


def build_server_config(server_name: str, peer_names: dict[str, str]) -> str:
    required = {"left", "right", "up", "down"}
    if set(peer_names) != required:
        raise ValueError("必须提供左、右、上、下四个客户端名称")
    lines = ["section: screens", f"    {server_name}:"]
    for direction in ("left", "right", "up", "down"):
        lines.append(f"    {peer_names[direction]}:")
    lines.extend(["end", "", "section: links", f"    {server_name}:"])
    for direction in ("left", "right", "up", "down"):
        lines.append(f"        {direction} = {peer_names[direction]}")
    for direction in ("left", "right", "up", "down"):
        lines.append(f"    {peer_names[direction]}:")
        lines.append(f"        {reverse_direction(direction)} = {server_name}")
    lines.extend([
        "end",
        "",
        "section: options",
        "    heartbeat = 3000",
        "    switchDelay = 0",
        "end",
        "",
    ])
    return "\n".join(lines)


def _write_settings(
    path: Path,
    *,
    computer_name: str,
    port: int,
    remote_host: str = "",
    server_config: PurePath | None = None,
    interface: str = "",
) -> None:
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.optionxform = str
    core = {
        "computerName": computer_name,
        "port": str(int(port)),
        "processMode": "1",  # Deskflow::Settings::Desktop
        "useHooks": "true",
    }
    if interface:
        core["interface"] = interface
    cfg["core"] = core
    cfg["security"] = {
        "tlsEnabled": "false",
        "checkPeerFingerprints": "false",
    }
    cfg["log"] = {"level": "4", "toFile": "false"}
    if remote_host:
        cfg["client"] = {
            "remoteHost": remote_host,
            "languageSync": "true",
        }
    if server_config is not None:
        cfg["server"] = {
            "externalConfig": "true",
            "externalConfigFile": _qsettings_path(server_config),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        cfg.write(fh, space_around_delimiters=False)


class DeskflowEngine:
    def __init__(self, status_cb: Callable[[str, str], None] | None = None):
        self.status_cb = status_cb or (lambda _kind, _text: None)
        self.server_process: subprocess.Popen | None = None
        self.client_process: subprocess.Popen | None = None
        self.bridge = TcpForwarder("0.0.0.0", DEFAULT_PORT, BACKEND_HOST, BACKEND_PORT)
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
        self.bridge.stop()
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

    def _wait_for_listener(self, proc: subprocess.Popen, host: str, port: int, timeout: float = 10.0) -> tuple[bool, str]:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                return False, f"Deskflow 已退出（退出码 {proc.returncode}）"
            probe = probe_tcp(host, port, timeout=0.35)
            if probe.ok:
                return True, "ok"
            last_error = probe.error
            time.sleep(0.18)
        return False, f"Deskflow 进程仍在运行，但 {host}:{port} 在 {timeout:.0f} 秒内始终没有真正开始监听。最后一次检测：{last_error or '无响应'}"

    def start_server(self, server_name: str, peer_names: dict[str, str], port: int = DEFAULT_PORT) -> tuple[bool, str]:
        self.stop_all()
        path = core_path()
        if not path.exists():
            return False, f"Deskflow 核心缺失：{path}"

        runtime = app_data_dir() / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        server_config = runtime / "deskflow-server.conf"
        settings = runtime / "deskflow-server-settings.ini"
        server_config.write_text(build_server_config(server_name, peer_names), "utf-8")

        # Keep Deskflow itself loopback-only.  The ShifanAI process owns the
        # LAN-facing TCP 24800 listener and forwards raw Deskflow traffic to the
        # backend.  This removes ambiguity around which adapter Deskflow binds
        # to and lets us verify the real public listener before reporting ready.
        _write_settings(
            settings,
            computer_name=server_name,
            port=BACKEND_PORT,
            server_config=server_config,
            interface=BACKEND_HOST,
        )
        ok, message, proc = self._spawn([str(path), "server", "--settings", str(settings)], "server")
        if not ok or proc is None:
            return False, message

        ready, detail = self._wait_for_listener(proc, BACKEND_HOST, BACKEND_PORT, timeout=10.0)
        if not ready:
            log = self.recent_log("server", 20)
            self._terminate(proc)
            with self._lock:
                self.server_process = None
            return False, f"Deskflow 后端没有真正启动监听：{detail}{' | 日志：' + log if log else ''}"

        bridge_ok, bridge_message = self.bridge.start()
        if not bridge_ok:
            self._terminate(proc)
            with self._lock:
                self.server_process = None
            return False, f"主控网络入口启动失败：{bridge_message}"

        public_probe = probe_tcp("127.0.0.1", port, timeout=1.2)
        if not public_probe.ok:
            self.bridge.stop()
            self._terminate(proc)
            with self._lock:
                self.server_process = None
            return False, f"TCP {port} 已创建但本机真实连接测试失败：{public_probe.error}"

        with self._lock:
            self.server_process = proc
            self._server_connected = False
        return True, f"主控端口已真实监听 0.0.0.0:{port}；Deskflow 后端 {BACKEND_HOST}:{BACKEND_PORT} 已就绪"

    def start_client(self, server_ip: str, client_name: str, port: int = DEFAULT_PORT) -> tuple[bool, str]:
        self.stop_all()
        path = core_path()
        if not path.exists():
            return False, f"Deskflow 核心缺失：{path}"
        runtime = app_data_dir() / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        settings = runtime / "deskflow-client-settings.ini"
        _write_settings(settings, computer_name=client_name, port=port, remote_host=server_ip)
        ok, message, proc = self._spawn([str(path), "client", "--settings", str(settings)], "client")
        if ok and proc is not None:
            with self._lock:
                self.client_process = proc
                self._client_connected = False
            return True, f"Deskflow 第二台电脑正在主动连接 {server_ip}:{port}"
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
        time.sleep(0.8)
        if proc.poll() is not None:
            log = self.recent_log(role, 16)
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
                del target[:-200]
            low = line.lower()
            if role == "server" and ("has connected" in low or "accepted client connection" in low):
                with self._lock:
                    self._server_connected = True
                self.status_cb("connected", "连接成功 · 鼠标可以直接跨屏，键盘会自动跟随")
            elif role == "client" and ("connected to server" in low or "ipc: connected to server" in low):
                with self._lock:
                    self._client_connected = True
                self.status_cb("remote_connected", "已连接主控电脑 · 正在接受键鼠控制")
            elif "unrecognised client name" in low or "server refused client with our name" in low:
                self.status_cb("pair_error", "配对码或屏幕方向与主控端授权不一致")
            elif "timed out" in low or "failed to connect" in low or "no route" in low:
                self.status_cb("network_error", line)
            elif "fatal" in low or "error:" in low or "critical" in low:
                self.status_cb("engine_error", line)

    def recent_log(self, role: str, count: int = 12) -> str:
        with self._lock:
            items = self._server_log if role == "server" else self._client_log
            return " | ".join(items[-count:])

    def status(self) -> dict:
        with self._lock:
            result = {
                "server_alive": bool(self.server_process and self.server_process.poll() is None),
                "client_alive": bool(self.client_process and self.client_process.poll() is None),
                "server_connected": self._server_connected,
                "client_connected": self._client_connected,
                "server_log": self._server_log[-6:],
                "client_log": self._client_log[-6:],
            }
        result["bridge"] = self.bridge.status()
        result["backend_port"] = BACKEND_PORT
        return result

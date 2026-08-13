from __future__ import annotations

import platform
import socket
import subprocess
import threading
import time

from .config import load_config, normalize_pair_code, regenerate_pair_code, save_config
from .deskflow_engine import DEFAULT_PORT, DESKFLOW_VERSION, DeskflowEngine, safe_screen_name
from .network_utils import list_lan_addresses, recommended_ip, validate_peer_ip
from .pairing import all_client_screen_names, client_screen_name

APP_VERSION = "0.7.1"


class AppApi:
    def __init__(self):
        self.cfg = load_config()
        self._status_lock = threading.RLock()
        self._status = {"kind": "ready", "text": "准备就绪", "detail": "选择这台电脑的角色即可开始"}
        self.engine = DeskflowEngine(self._engine_status)
        self.role = "idle"

    def close(self) -> None:
        self.engine.stop_all()

    def _set_status(self, kind: str, text: str, detail: str = "") -> None:
        with self._status_lock:
            self._status = {"kind": kind, "text": text, "detail": detail, "time": int(time.time()), "role": self.role}

    def _engine_status(self, kind: str, text: str) -> None:
        if kind == "connected":
            self._set_status("connected", text, f"Deskflow TCP {DEFAULT_PORT} · 主控电脑")
        elif kind == "remote_connected":
            self._set_status("remote", text, f"Deskflow TCP {DEFAULT_PORT} · 第二台电脑")
        elif kind == "pair_error":
            self._set_status("error", "配对失败", text)
        elif kind == "network_error":
            self._set_status("error", "主控电脑暂时无法连接", self._friendly_network_log(text))
        elif kind == "engine_error":
            self._set_status("error", "Deskflow 运行异常", text)

    def _friendly_network_log(self, line: str) -> str:
        low = line.lower()
        if "timed out" in low:
            return f"TCP {DEFAULT_PORT} 连接超时。请确认主控电脑已经点击“启动主控模式”，且两台电脑在同一局域网。"
        if "no route" in low:
            return "系统当前没有到主控电脑的可用网络路由，请检查两台电脑是否连接同一个路由器/交换机。"
        return line

    def get_state(self) -> dict:
        addresses = list_lan_addresses()
        available, engine_path = self.engine.available()
        return {
            "version": APP_VERSION,
            "device": {
                "name": socket.gethostname(),
                "id": self.cfg["device_id"],
                "pair_code": self.cfg["pair_code"],
                "recommended_ip": recommended_ip(),
                "addresses": [
                    {"interface": a.interface, "ip": a.ip, "recommended": a.recommended, "virtual": getattr(a, "virtual", False)}
                    for a in addresses
                ],
                "kvm_port": DEFAULT_PORT,
            },
            "peer": self.cfg.get("peer", {}),
            "engine": {"available": available, "path": engine_path, "version": DESKFLOW_VERSION},
            "os": platform.system(),
            "role": self.role,
        }

    def get_status(self) -> dict:
        with self._status_lock:
            status = dict(self._status)
        status["engine"] = self.engine.status()
        status["role"] = self.role
        return status

    def regenerate_code(self) -> dict:
        was_host = self.role == "host"
        code = regenerate_pair_code(self.cfg)
        if was_host:
            # Restart the server so only names derived from the new code are accepted.
            result = self.prepare_host()
            if not result.get("ok"):
                return result
        self._set_status("host_waiting" if was_host else "ready", "配对码已更新", "旧配对码立即失效")
        return {"ok": True, "pair_code": code}

    def prepare_host(self) -> dict:
        self.role = "host"
        server_name = safe_screen_name("HOST", self.cfg["device_id"])
        peer_names = all_client_screen_names(self.cfg["pair_code"])
        self._set_status("connecting", "正在启动主控模式…", f"Deskflow 将直接监听 TCP {DEFAULT_PORT}，不再使用额外配对端口")
        ok, message = self.engine.start_server(server_name, peer_names, DEFAULT_PORT)
        if not ok:
            self.role = "idle"
            self._set_status("error", "主控模式启动失败", message)
            return {"ok": False, "error": message}
        self._set_status(
            "host_waiting",
            "主控模式已开启 · 等待第二台电脑",
            f"第二台电脑只需输入本机 IP {recommended_ip()} + 配对码，然后直接连接 TCP {DEFAULT_PORT}",
        )
        return {"ok": True, "host_ip": recommended_ip(), "pair_code": self.cfg["pair_code"], "port": DEFAULT_PORT}

    def connect(self, payload: dict) -> dict:
        host = ""
        try:
            host = validate_peer_ip(str(payload.get("host", "")))
            pair_code = str(payload.get("pair_code", "")).strip()
            direction = str(payload.get("direction", "right"))
            if direction not in {"left", "right", "up", "down"}:
                raise ValueError("请选择本机屏幕相对主控电脑的位置")
            if len(normalize_pair_code(pair_code)) != 12:
                raise ValueError("请完整输入主控电脑显示的 12 位配对码")
            if host in {a.ip for a in list_lan_addresses()}:
                raise ValueError("这里要填写主控电脑 IP，不能填写本机 IP")

            self.role = "client"
            client_name = client_screen_name(pair_code, direction)
            self._set_status(
                "connecting",
                "正在连接主控电脑…",
                f"Deskflow 直接连接 {host}:{DEFAULT_PORT} · 不再经过 35999/其他自定义端口",
            )
            ok, message = self.engine.start_client(host, client_name, DEFAULT_PORT)
            if not ok:
                self.role = "idle"
                self._set_status("error", "第二台电脑启动失败", message)
                return {"ok": False, "error": message, "code": "START"}

            self.cfg["peer"] = {
                "host": host,
                "pair_code": pair_code,
                "direction": direction,
                "device_name": "",
                "device_id": "",
            }
            save_config(self.cfg)
            return {"ok": True, "host": host, "port": DEFAULT_PORT}
        except Exception as exc:
            self.role = "idle"
            self.engine.stop_all()
            self._set_status("error", "无法启动连接", str(exc))
            return {"ok": False, "error": str(exc), "code": "VALIDATION"}

    def disconnect(self) -> dict:
        self.engine.stop_all()
        self.role = "idle"
        self._set_status("ready", "共享已停止", "可以重新选择主控电脑或第二台电脑")
        return {"ok": True}

    def open_system_permissions(self) -> dict:
        if platform.system() != "Darwin":
            return {"ok": True}
        try:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
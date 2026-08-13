from __future__ import annotations

import platform
import socket
import threading
import time

from .config import load_config, regenerate_pair_code, save_config
from .deskflow_engine import DESKFLOW_VERSION, DeskflowEngine, safe_screen_name
from .network_utils import list_lan_addresses, recommended_ip, route_ip_to, validate_peer_ip
from .pairing import PairingClient, PairingService

APP_VERSION = "0.3.0"


class AppApi:
    def __init__(self):
        self.cfg = load_config()
        self._status_lock = threading.RLock()
        self._status = {"kind": "ready", "text": "准备就绪 · 等待连接", "detail": ""}
        self.engine = DeskflowEngine(self._engine_status)
        self.service = PairingService("0.0.0.0", int(self.cfg["control_port"]), lambda: self.cfg["pair_code"], self._device_info, self._remote_start_client, self.engine.stop_client, lambda text: self._set_status("ready", "本机已就绪", text))
        self.service.start()

    def close(self) -> None:
        self.engine.stop_all(); self.service.stop()

    def _device_info(self) -> dict:
        return {"device_name": socket.gethostname(), "device_id": self.cfg["device_id"], "version": APP_VERSION, "os": platform.system()}

    def _set_status(self, kind: str, text: str, detail: str = "") -> None:
        with self._status_lock: self._status = {"kind": kind, "text": text, "detail": detail, "time": int(time.time())}

    def _engine_status(self, kind: str, text: str) -> None:
        if kind == "connected": self._set_status("connected", text, "键鼠通道运行中")
        elif kind == "remote_connected": self._set_status("remote", text, "本机当前作为第二台电脑")
        elif kind == "engine_log":
            with self._status_lock:
                if self._status.get("kind") not in {"connected", "remote"}: self._status["detail"] = text

    def _remote_start_client(self, server_ip: str, server_port: int, client_name: str) -> tuple[bool, str]:
        ok, message = self.engine.start_client(server_ip, server_port, client_name)
        self._set_status("connecting" if ok else "error", message, f"主控电脑 {server_ip}")
        return ok, message

    def get_state(self) -> dict:
        addresses = list_lan_addresses(); available, engine_path = self.engine.available()
        return {"version": APP_VERSION, "device": {"name": socket.gethostname(), "id": self.cfg["device_id"], "pair_code": self.cfg["pair_code"], "recommended_ip": addresses[0].ip if addresses else recommended_ip(), "addresses": [{"interface": a.interface, "ip": a.ip, "recommended": a.recommended} for a in addresses], "control_port": self.cfg["control_port"]}, "peer": self.cfg.get("peer", {}), "engine": {"available": available, "path": engine_path, "version": DESKFLOW_VERSION}, "os": platform.system()}

    def get_status(self) -> dict:
        with self._status_lock: status = dict(self._status)
        status["engine"] = self.engine.status(); return status

    def regenerate_code(self) -> dict:
        code = regenerate_pair_code(self.cfg); self._set_status("ready", "配对码已更新", "旧配对码立即失效"); return {"ok": True, "pair_code": code}

    def connect(self, payload: dict) -> dict:
        try:
            host = validate_peer_ip(str(payload.get("host", "")))
            pair_code = str(payload.get("pair_code", "")).strip()
            direction = str(payload.get("direction", "right"))
            if direction not in {"left", "right", "up", "down"}: raise ValueError("请选择第二台屏幕的真实位置")
            if len("".join(ch for ch in pair_code if ch.isalnum())) < 8: raise ValueError("请完整输入第二台电脑显示的配对码")
            if host in {a.ip for a in list_lan_addresses()}: raise ValueError("这里要填写第二台电脑的 IP，不能填写本机 IP")
            control_port = int(self.cfg["control_port"])
            self._set_status("connecting", "正在识别第二台电脑…", f"{host}:{control_port}")
            probe = PairingClient.probe(host, control_port)
            if probe.version and probe.version != APP_VERSION: raise ConnectionError(f"两台电脑版本不同：本机 {APP_VERSION} / 第二台 {probe.version}，请安装同一版本")
            local_route_ip = route_ip_to(host, control_port)
            server_name = safe_screen_name("HOST", self.cfg["device_id"]); client_name = safe_screen_name("PEER", probe.device_id); kvm_port = int(self.cfg["kvm_port"])
            self._set_status("connecting", "正在启动本机键鼠共享核心…", f"通过 {local_route_ip} 连接 {probe.device_name}")
            ok, message = self.engine.start_server(server_name, client_name, direction, kvm_port)
            if not ok: raise RuntimeError(message)
            self._set_status("connecting", "正在授权第二台电脑…", "配对码正在本地校验，不会明文发送")
            response = PairingClient.start_remote_client(host, control_port, pair_code, local_route_ip, kvm_port, client_name)
            if not response.get("ok"):
                self.engine.stop_server(); raise PermissionError(str(response.get("error") or response.get("message") or "第二台电脑拒绝连接"))
            self.cfg["peer"] = {"host": host, "pair_code": pair_code, "direction": direction, "device_name": probe.device_name, "device_id": probe.device_id}; save_config(self.cfg)
            self._set_status("connecting", f"已通过配对 · 正在建立 {probe.device_name} 键鼠通道", "通常 1-3 秒完成")
            return {"ok": True, "peer_name": probe.device_name, "local_route_ip": local_route_ip}
        except PermissionError as exc:
            self._set_status("error", "配对失败", str(exc)); return {"ok": False, "error": str(exc), "code": "PAIR_CODE"}
        except (ConnectionError, OSError) as exc:
            self.engine.stop_server(); text = f"无法连接第二台电脑：{exc}"; self._set_status("error", "连接失败", text); return {"ok": False, "error": text, "code": "NETWORK"}
        except Exception as exc:
            self.engine.stop_server(); self._set_status("error", "启动失败", str(exc)); return {"ok": False, "error": str(exc), "code": "START"}

    def disconnect(self) -> dict:
        peer = self.cfg.get("peer") or {}
        if peer.get("host") and peer.get("pair_code"): PairingClient.stop_remote_client(str(peer["host"]), int(self.cfg["control_port"]), str(peer["pair_code"]))
        self.engine.stop_server(); self._set_status("ready", "共享已停止", "本机配对服务仍在运行"); return {"ok": True}

    def open_system_permissions(self) -> dict:
        if platform.system() != "Darwin": return {"ok": True}
        import subprocess
        try:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"]); return {"ok": True}
        except Exception as exc: return {"ok": False, "error": str(exc)}

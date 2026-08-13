from __future__ import annotations

import platform
import socket
import subprocess
import threading
import time

from .config import load_config, normalize_pair_code, regenerate_pair_code, save_config
from .deskflow_engine import DESKFLOW_VERSION, DeskflowEngine, safe_screen_name
from .network_utils import list_lan_addresses, physical_lan_addresses, recommended_ip, route_ip_to, same_local_subnet, validate_peer_ip
from .pairing import PairingClient, PairingService

APP_VERSION = "0.6.0"
CONTROL_PORT = 35999
KVM_PORT = 24800


class AppApi:
    def __init__(self):
        self.cfg = load_config()
        self._status_lock = threading.RLock()
        self._status = {"kind": "ready", "text": "准备就绪", "detail": "请选择本机作为主控或第二台电脑"}
        self.engine = DeskflowEngine(self._engine_status)
        self.role = "idle"
        self.host_ready = False
        self.service = PairingService(
            "0.0.0.0",
            CONTROL_PORT,
            lambda: self.cfg["pair_code"],
            self._device_info,
            self._authorize_client,
            lambda text: self._set_status("ready", "本机网络服务已就绪", text),
        )
        self.service.start()

    def close(self) -> None:
        self.engine.stop_all()
        self.service.stop()

    def _device_info(self) -> dict:
        return {
            "device_name": socket.gethostname(),
            "device_id": self.cfg["device_id"],
            "version": APP_VERSION,
            "os": platform.system(),
            "host_ready": self.host_ready,
            "role": self.role,
        }

    def _set_status(self, kind: str, text: str, detail: str = "") -> None:
        with self._status_lock:
            self._status = {"kind": kind, "text": text, "detail": detail, "time": int(time.time()), "role": self.role}

    def _engine_status(self, kind: str, text: str) -> None:
        if kind == "connected":
            self._set_status("connected", text, "Deskflow TCP 24800 · 主控端")
        elif kind == "remote_connected":
            self._set_status("remote", text, "Deskflow TCP 24800 · 第二台电脑")
        elif kind == "engine_log":
            with self._status_lock:
                if self._status.get("kind") not in {"connected", "remote"}:
                    self._status["detail"] = text

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
                    {"interface": a.interface, "ip": a.ip, "recommended": a.recommended, "virtual": a.virtual}
                    for a in addresses
                ],
                "control_port": CONTROL_PORT,
                "kvm_port": KVM_PORT,
            },
            "peer": self.cfg.get("peer", {}),
            "engine": {"available": available, "path": engine_path, "version": DESKFLOW_VERSION},
            "os": platform.system(),
            "role": self.role,
            "host_ready": self.host_ready,
        }

    def get_status(self) -> dict:
        with self._status_lock:
            status = dict(self._status)
        status["engine"] = self.engine.status()
        status["role"] = self.role
        status["host_ready"] = self.host_ready
        return status

    def regenerate_code(self) -> dict:
        code = regenerate_pair_code(self.cfg)
        self._set_status("ready", "配对码已更新", "旧配对码立即失效")
        return {"ok": True, "pair_code": code}

    def prepare_host(self) -> dict:
        self.engine.stop_all()
        self.role = "host"
        self.host_ready = True
        self._set_status(
            "host_waiting",
            "主控模式已开启 · 等待第二台电脑",
            f"第二台电脑请输入本机 IP {recommended_ip()} 和上方配对码；只需第二台电脑主动连接本机 TCP {CONTROL_PORT}",
        )
        return {"ok": True, "host_ip": recommended_ip(), "pair_code": self.cfg["pair_code"], "control_port": CONTROL_PORT}

    def _authorize_client(self, client_name: str, direction: str) -> tuple[bool, str, int]:
        if not self.host_ready or self.role != "host":
            return False, "这台电脑尚未开启主控模式，请先点击“将本机设为主控电脑”", KVM_PORT
        server_name = safe_screen_name("HOST", self.cfg["device_id"])
        listen_ip = recommended_ip()
        self._set_status("connecting", "第二台电脑配对成功 · 正在启动 Deskflow", f"监听 {listen_ip}:{KVM_PORT}")
        ok, message = self.engine.start_server(server_name, client_name, direction, KVM_PORT, listen_ip=listen_ip)
        if ok:
            self.cfg["peer"] = {"host": "", "pair_code": "", "direction": direction, "device_name": client_name, "device_id": ""}
            save_config(self.cfg)
        else:
            self._set_status("error", "Deskflow 主控启动失败", message)
        return ok, message, KVM_PORT

    def _route_summary(self, host: str) -> str:
        try:
            route_ip = route_ip_to(host, CONTROL_PORT)
        except OSError:
            route_ip = "未找到"
        physical = ", ".join(f"{a.interface}={a.ip}" for a in physical_lan_addresses()) or "未识别"
        return f"系统路由源地址：{route_ip}；物理局域网：{physical}"

    def _network_error(self, host: str, exc: BaseException) -> str:
        winerror = getattr(exc, "winerror", None)
        errno = getattr(exc, "errno", None)
        code = winerror or errno
        route = self._route_summary(host)
        subnet = same_local_subnet(host)
        if code == 10051:
            return (
                f"Windows 返回 10051：当前系统路由表认为 {host} 不可达。{route}。"
                f"同物理子网判断：{'是' if subnet else '否'}。这不是配对码错误，也不再归因于 VPN。"
            )
        if code == 10061:
            return (
                f"已到达 {host}，但 TCP {CONTROL_PORT} 被拒绝，说明对方没有监听该端口。"
                "请确认对方安装 v0.6.0、软件保持打开，并已点击“将本机设为主控电脑”。"
            )
        if code in {10060, 110, 60} or isinstance(exc, socket.timeout) or "timed out" in str(exc).lower():
            return (
                f"到 {host} 的网络路由存在，但 TCP {CONTROL_PORT} 在 2.5 秒内没有响应。{route}。"
                "这通常是主控端防火墙/安全软件拦截，或路由器开启了 AP/客户端隔离。"
            )
        if code in {10013, 13}:
            return (
                f"本机 Windows/安全软件拒绝了 TCP 连接（10013）。{route}。"
                "这是本机侧访问被拒绝，不代表第二台电脑没开软件。"
            )
        return f"连接主控电脑失败：{exc}。{route}"

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

            self.engine.stop_all()
            self.role = "client"
            self.host_ready = False
            self._set_status("connecting", "正在连接主控电脑…", f"{host}:{CONTROL_PORT} · 使用 Windows/macOS 系统原生路由，不再强绑虚拟网卡")
            probe = PairingClient.probe(host, CONTROL_PORT)
            if probe.version and probe.version != APP_VERSION:
                raise ConnectionError(f"两台电脑版本不同：本机 {APP_VERSION} / 主控 {probe.version}，请两边都安装 v0.6.0")
            if not probe.host_ready or probe.role != "host":
                raise ConnectionError(f"已找到 {probe.device_name}，但它还没有开启主控模式。请先在那台电脑点击“将本机设为主控电脑”")

            client_name = safe_screen_name("PEER", self.cfg["device_id"])
            auth = PairingClient.authorize_client(host, CONTROL_PORT, pair_code, client_name, direction)
            if not auth.get("ok"):
                raise PermissionError(str(auth.get("error") or auth.get("message") or "主控电脑拒绝配对"))

            server_port = int(auth.get("server_port") or KVM_PORT)
            self._set_status("connecting", "配对通过 · 正在启动第二台电脑 Deskflow", f"主动连接 {host}:{server_port}")
            ok, message = self.engine.start_client(host, server_port, client_name)
            if not ok:
                raise RuntimeError(message)

            self.cfg["peer"] = {"host": host, "pair_code": pair_code, "direction": direction, "device_name": probe.device_name, "device_id": probe.device_id}
            save_config(self.cfg)
            return {"ok": True, "peer_name": probe.device_name, "server_port": server_port}
        except PermissionError as exc:
            self.role = "idle"
            self.engine.stop_all()
            self._set_status("error", "配对失败", str(exc))
            return {"ok": False, "error": str(exc), "code": "PAIR_CODE"}
        except (ConnectionError, OSError, TimeoutError) as exc:
            self.role = "idle"
            self.engine.stop_all()
            text = self._network_error(host, exc) if isinstance(exc, OSError) else str(exc)
            self._set_status("error", "网络连接失败", text)
            return {"ok": False, "error": text, "code": "NETWORK"}
        except Exception as exc:
            self.role = "idle"
            self.engine.stop_all()
            self._set_status("error", "启动失败", str(exc))
            return {"ok": False, "error": str(exc), "code": "START"}

    def diagnose_host(self, host: str) -> dict:
        try:
            host = validate_peer_ip(host)
            route = self._route_summary(host)
            probe = PairingClient.probe(host, CONTROL_PORT, timeout=2.5)
            return {
                "ok": True,
                "text": f"TCP {CONTROL_PORT} 可达，识别到 {probe.device_name} v{probe.version}；主控模式：{'已开启' if probe.host_ready else '未开启'}。{route}",
            }
        except Exception as exc:
            if isinstance(exc, OSError):
                text = self._network_error(host, exc)
            else:
                text = f"网络自检失败：{exc}。{self._route_summary(host)}"
            return {"ok": False, "text": text}

    def disconnect(self) -> dict:
        self.engine.stop_all()
        self.role = "idle"
        self.host_ready = False
        self._set_status("ready", "共享已停止", "可以重新选择主控或第二台电脑")
        return {"ok": True}

    def open_system_permissions(self) -> dict:
        if platform.system() != "Darwin":
            return {"ok": True}
        try:
            subprocess.Popen(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

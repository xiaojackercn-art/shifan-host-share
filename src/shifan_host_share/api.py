from __future__ import annotations

import platform
import socket
import subprocess
import threading
import time

from .config import load_config, normalize_pair_code, regenerate_pair_code, save_config
from .deskflow_engine import DEFAULT_PORT, DESKFLOW_VERSION, DeskflowEngine, safe_screen_name
from .lan_bridge import ProbeResult, probe_tcp_until
from .network_utils import list_lan_addresses, recommended_ip, same_local_subnet, validate_peer_ip
from .pairing import all_client_screen_names, client_screen_name
from .windows_firewall import ensure_windows_firewall

APP_VERSION = "0.9.0"


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
            self._set_status("connected", text, f"TCP {DEFAULT_PORT} · 主控电脑 · Deskflow 协议握手完成")
        elif kind == "remote_connected":
            self._set_status("remote", text, f"TCP {DEFAULT_PORT} · 第二台电脑 · Deskflow 协议握手完成")
        elif kind == "client_disconnected":
            self._set_status("host_waiting", text, f"主控 TCP {DEFAULT_PORT} 仍保持监听")
        elif kind == "remote_disconnected":
            self._set_status("connecting", text, f"Deskflow Client 仍在运行，将继续尝试连接 TCP {DEFAULT_PORT}")
        elif kind == "pair_error":
            self._set_status("error", "配对失败", text)
        elif kind == "network_error":
            self._set_status("error", "主控电脑暂时无法连接", self._friendly_engine_network_log(text))
        elif kind == "engine_error":
            self._set_status("error", "Deskflow 运行异常", text)

    def _friendly_engine_network_log(self, line: str) -> str:
        low = line.lower()
        if "timed out" in low:
            return f"Deskflow 与主控 TCP {DEFAULT_PORT} 通信超时。软件已保留底层日志用于继续定位。"
        if "no route" in low:
            return "系统当前没有到主控电脑的可用网络路由。"
        return line

    def _probe_error(self, host: str, result: ProbeResult, *, firewall_detail: str = "") -> str:
        code = result.winerror
        low = result.error.lower()
        subnet_hint = ""
        try:
            subnet_hint = "两台电脑看起来位于同一物理子网。" if same_local_subnet(host) else "主控 IP 不在本机检测到的物理子网内，请确认两台电脑之间存在可路由网络。"
        except Exception:
            pass
        firewall_hint = f" Windows 防火墙检查：{firewall_detail}。" if firewall_detail else ""
        if code in {10060, 110, 60} or "timed out" in low:
            return (
                f"主控电脑 {host}:{DEFAULT_PORT} 在连接窗口内没有接受 TCP 连接。"
                f"{subnet_hint}{firewall_hint}"
                "v0.9 已不再把本机探测当作真实第二台电脑连接；如果这里仍超时，说明数据包没有从第二台电脑真正到达主控 24800。"
            )
        if code in {10061, 111, 61} or "refused" in low:
            return (
                f"已经到达主控电脑 {host}，但 TCP {DEFAULT_PORT} 被拒绝。"
                f"{firewall_hint}请确认主控端仍显示“主控等待中”，并且没有被其他程序占用端口。"
            )
        if code in {10051, 101, 51} or "unreachable" in low or "no route" in low:
            return f"系统没有到 {host} 的可用网络路由。{subnet_hint}{firewall_hint}"
        return f"无法连接主控电脑 {host}:{DEFAULT_PORT}：{result.error}.{firewall_hint}"

    @staticmethod
    def _cancelled(cancel_event: threading.Event | None) -> bool:
        return bool(cancel_event is not None and cancel_event.is_set())

    def _cancel_result(self, *, cleanup: bool = True) -> dict:
        if cleanup:
            self.engine.stop_all()
        self.role = "idle"
        self._set_status("ready", "操作已取消", "可以重新选择主控电脑或第二台电脑")
        return {"ok": False, "cancelled": True, "error": "操作已取消"}

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
            "connection_mode": "direct-ip",
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
            result = self.prepare_host()
            if not result.get("ok"):
                return result
        self._set_status("host_waiting" if was_host else "ready", "配对码已更新", "旧配对码立即失效")
        return {"ok": True, "pair_code": code}

    def prepare_host(self, cancel_event: threading.Event | None = None) -> dict:
        if self._cancelled(cancel_event):
            return self._cancel_result()
        self.role = "host"
        host_ip = recommended_ip()
        server_name = safe_screen_name("HOST", self.cfg["device_id"])
        peer_names = all_client_screen_names(self.cfg["pair_code"])

        firewall_detail = ""
        if platform.system() == "Windows":
            self._set_status(
                "connecting",
                "正在检查 Windows 局域网权限…",
                f"确认 TCP {DEFAULT_PORT} 入站规则；安装版通常无需再次授权，便携版首次使用可能弹出 UAC。",
            )
            fw_ok, firewall_detail = ensure_windows_firewall("in", DEFAULT_PORT)
            if self._cancelled(cancel_event):
                return self._cancel_result()
            if not fw_ok:
                self.role = "idle"
                detail = f"Windows 防火墙 TCP {DEFAULT_PORT} 入站授权未完成：{firewall_detail}"
                self._set_status("error", "主控网络权限未准备好", detail)
                return {"ok": False, "error": detail, "code": "FIREWALL"}

        self._set_status(
            "connecting",
            "正在启动主控模式…",
            "正在启动 Deskflow 本机后端和视饭AI TCP 24800 网络入口",
        )
        ok, message = self.engine.start_server(server_name, peer_names, DEFAULT_PORT, cancel_event=cancel_event)
        if not ok:
            if message == "操作已取消" or self._cancelled(cancel_event):
                return self._cancel_result()
            self.role = "idle"
            self._set_status("error", "主控模式启动失败", message)
            return {"ok": False, "error": message, "code": "START"}

        if self._cancelled(cancel_event):
            return self._cancel_result()

        # This verifies that the app really bound the LAN-facing address.  It is
        # not treated as a remote Deskflow connection; only a completed Deskflow
        # protocol handshake can change the UI to “已连接”.
        lan_probe = probe_tcp_until(
            host_ip,
            DEFAULT_PORT,
            total_timeout=1.8,
            attempt_timeout=0.3,
            cancel_event=cancel_event,
        )
        if not lan_probe.ok:
            if lan_probe.error == "操作已取消" or self._cancelled(cancel_event):
                return self._cancel_result()
            self.engine.stop_all()
            self.role = "idle"
            detail = self._probe_error(host_ip, lan_probe, firewall_detail=firewall_detail)
            self._set_status("error", "主控局域网入口验证失败", detail)
            return {"ok": False, "error": detail, "code": "LISTENER"}

        self._set_status(
            "host_waiting",
            "主控模式已开启 · 等待第二台电脑",
            f"{host_ip}:{DEFAULT_PORT} 已监听；{firewall_detail or '网络权限已准备'}。只有第二台电脑完成 Deskflow 协议握手后才会显示“已连接”。",
        )
        return {"ok": True, "host_ip": host_ip, "pair_code": self.cfg["pair_code"], "port": DEFAULT_PORT}

    def connect(self, payload: dict, cancel_event: threading.Event | None = None) -> dict:
        host = ""
        firewall_detail = ""
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
            if self._cancelled(cancel_event):
                return self._cancel_result()

            self.role = "client"
            if platform.system() == "Windows":
                self._set_status(
                    "connecting",
                    "正在检查 Windows 网络权限…",
                    f"确认本机允许向主控 TCP {DEFAULT_PORT} 发起连接",
                )
                fw_ok, firewall_detail = ensure_windows_firewall("out", DEFAULT_PORT)
                if self._cancelled(cancel_event):
                    return self._cancel_result()
                # Outbound is allowed by default on normal Windows installs.  If
                # the repair itself cannot elevate, still perform the real TCP
                # test; a successful TCP connection is stronger evidence than
                # the firewall-rule query.
                if not fw_ok:
                    firewall_detail = f"自动出站规则未确认（{firewall_detail}）"

            self._set_status(
                "connecting",
                "正在检测主控电脑…",
                f"正在真实连接 {host}:{DEFAULT_PORT}；此过程可随时点击“取消连接”",
            )
            preflight = probe_tcp_until(
                host,
                DEFAULT_PORT,
                total_timeout=3.5,
                attempt_timeout=0.4,
                cancel_event=cancel_event,
            )
            if not preflight.ok:
                if preflight.error == "操作已取消" or self._cancelled(cancel_event):
                    return self._cancel_result()
                raise ConnectionError(self._probe_error(host, preflight, firewall_detail=firewall_detail))

            if self._cancelled(cancel_event):
                return self._cancel_result()

            client_name = client_screen_name(pair_code, direction)
            self._set_status(
                "connecting",
                "主控端口可达 · 正在完成 Deskflow 握手…",
                f"TCP {host}:{DEFAULT_PORT} 已连通，正在验证配对码和屏幕方向",
            )
            ok, message = self.engine.start_client(host, client_name, DEFAULT_PORT, cancel_event=cancel_event)
            if not ok:
                if message == "操作已取消" or self._cancelled(cancel_event):
                    return self._cancel_result()
                self.role = "idle"
                self._set_status("error", "第二台电脑启动失败", message)
                return {"ok": False, "error": message, "code": "START"}

            handshake_ok, handshake_detail = self.engine.wait_for_client_connection(timeout=10.0, cancel_event=cancel_event)
            if not handshake_ok:
                if handshake_detail == "操作已取消" or self._cancelled(cancel_event):
                    return self._cancel_result()
                self.engine.stop_all()
                self.role = "idle"
                self._set_status("error", "Deskflow 连接没有完成", handshake_detail)
                return {"ok": False, "error": handshake_detail, "code": "HANDSHAKE"}

            self.cfg["peer"] = {
                "host": host,
                "pair_code": pair_code,
                "direction": direction,
                "device_name": "",
                "device_id": "",
            }
            save_config(self.cfg)
            self._set_status(
                "remote",
                "已连接主控电脑 · 可以开始跨屏",
                f"Deskflow 协议握手完成 · TCP {host}:{DEFAULT_PORT}",
            )
            return {"ok": True, "host": host, "port": DEFAULT_PORT}
        except ConnectionError as exc:
            self.role = "idle"
            self.engine.stop_all()
            self._set_status("error", "主控电脑无法连接", str(exc))
            return {"ok": False, "error": str(exc), "code": "NETWORK"}
        except Exception as exc:
            self.role = "idle"
            self.engine.stop_all()
            self._set_status("error", "无法启动连接", str(exc))
            return {"ok": False, "error": str(exc), "code": "VALIDATION"}

    def disconnect(self) -> dict:
        self._set_status("stopping", "正在停止共享…", "正在关闭 Deskflow 和 TCP 转发")
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

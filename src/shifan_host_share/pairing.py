from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import socket
import socketserver
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .config import normalize_pair_code

PROTOCOL_VERSION = 3
MAX_LINE = 64 * 1024
CLOCK_SKEW = 90


def _key(pair_code: str) -> bytes:
    normalized = normalize_pair_code(pair_code)
    return hashlib.sha256(("SHIFANAI-PAIR-V3|" + normalized).encode()).digest()


def _canonical(payload: dict) -> bytes:
    filtered = {k: v for k, v in payload.items() if k != "proof"}
    return json.dumps(filtered, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sign_payload(payload: dict, pair_code: str) -> str:
    return hmac.new(_key(pair_code), _canonical(payload), hashlib.sha256).hexdigest()


def verify_payload(payload: dict, pair_code: str, now: int | None = None) -> bool:
    proof = str(payload.get("proof", ""))
    if not proof:
        return False
    try:
        ts = int(payload.get("timestamp", 0))
    except (TypeError, ValueError):
        return False
    now = int(time.time()) if now is None else int(now)
    if abs(now - ts) > CLOCK_SKEW:
        return False
    return hmac.compare_digest(proof, sign_payload(payload, pair_code))


@dataclass
class ProbeInfo:
    device_name: str
    device_id: str
    version: str
    host_ready: bool
    role: str


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class PairingService:
    """Small control channel that lives on the future Deskflow server only.

    The important v0.6 design rule is directional: the secondary computer makes
    every network connection to the host. The host never opens a TCP connection
    back to the secondary computer.
    """

    def __init__(
        self,
        host: str,
        port: int,
        pair_code_provider: Callable[[], str],
        device_info_provider: Callable[[], dict],
        on_authorize_client: Callable[[str, str], tuple[bool, str, int]],
        on_status: Callable[[str], None] | None = None,
    ):
        self.host = host
        self.port = int(port)
        self.pair_code_provider = pair_code_provider
        self.device_info_provider = device_info_provider
        self.on_authorize_client = on_authorize_client
        self.on_status = on_status or (lambda _: None)
        self._server: _ThreadingTCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        service = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:
                self.connection.settimeout(8)
                raw = self.rfile.readline(MAX_LINE)
                if not raw:
                    return
                try:
                    req = json.loads(raw.decode("utf-8"))
                    if not isinstance(req, dict):
                        raise ValueError("request must be an object")
                    response = service._handle(req)
                except Exception as exc:
                    response = {"ok": False, "error": f"请求格式错误：{exc}"}
                self.wfile.write((json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))

        self._server = _ThreadingTCPServer((self.host, self.port), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, name="pairing-service", daemon=True)
        self._thread.start()
        self.on_status(f"本地配对服务已监听 TCP {self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None

    def _handle(self, req: dict) -> dict:
        if req.get("protocol") != PROTOCOL_VERSION:
            return {"ok": False, "error": "软件协议版本不同，请两台电脑都安装 v0.6.0"}
        action = req.get("action")
        if action == "probe":
            return {"ok": True, **self.device_info_provider()}
        if action != "authorize_client":
            return {"ok": False, "error": "不支持的操作"}
        if not verify_payload(req, self.pair_code_provider()):
            return {"ok": False, "error": "配对码不正确，请输入主控电脑显示的配对码"}

        client_name = str(req.get("client_name", "")).strip()
        direction = str(req.get("direction", "right")).strip()
        if not client_name:
            return {"ok": False, "error": "第二台电脑名称无效"}
        if direction not in {"left", "right", "up", "down"}:
            return {"ok": False, "error": "屏幕位置无效"}
        ok, message, server_port = self.on_authorize_client(client_name, direction)
        return {"ok": ok, "message": message, "error": "" if ok else message, "server_port": int(server_port)}


class PairingClient:
    @staticmethod
    def _request(host: str, port: int, payload: dict, timeout: float = 3.0) -> dict:
        """Use the OS routing table exactly like Deskflow does.

        v0.5 tried to bind sockets to individual Wi-Fi/WSL/VPN addresses. That
        could manufacture WSAENETUNREACH (10051) even when another route was
        valid. v0.6 deliberately does not bind a source address.
        """
        data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(data)
            file = sock.makefile("rb")
            raw = file.readline(MAX_LINE)
        if not raw:
            raise ConnectionError("主控电脑没有返回配对数据")
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ConnectionError("主控电脑返回数据格式错误")
        return result

    @classmethod
    def probe(cls, host: str, port: int, timeout: float = 2.5) -> ProbeInfo:
        payload = {"protocol": PROTOCOL_VERSION, "action": "probe", "nonce": secrets.token_hex(12)}
        result = cls._request(host, port, payload, timeout=timeout)
        if not result.get("ok"):
            raise ConnectionError(str(result.get("error", "无法识别主控电脑")))
        return ProbeInfo(
            str(result.get("device_name", host)),
            str(result.get("device_id", "")),
            str(result.get("version", "")),
            bool(result.get("host_ready")),
            str(result.get("role", "idle")),
        )

    @classmethod
    def authorize_client(
        cls,
        host: str,
        port: int,
        pair_code: str,
        client_name: str,
        direction: str,
    ) -> dict:
        payload = {
            "protocol": PROTOCOL_VERSION,
            "action": "authorize_client",
            "timestamp": int(time.time()),
            "nonce": secrets.token_hex(16),
            "client_name": client_name,
            "direction": direction,
        }
        payload["proof"] = sign_payload(payload, pair_code)
        return cls._request(host, port, payload, timeout=7.0)

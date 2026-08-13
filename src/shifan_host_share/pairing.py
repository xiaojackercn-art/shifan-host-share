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

PROTOCOL_VERSION = 2
MAX_LINE = 64 * 1024
CLOCK_SKEW = 90


def _key(pair_code: str) -> bytes:
    normalized = normalize_pair_code(pair_code)
    return hashlib.sha256(("SHIFANAI-PAIR-V2|" + normalized).encode()).digest()


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
    expected = sign_payload(payload, pair_code)
    return hmac.compare_digest(proof, expected)


@dataclass
class ProbeInfo:
    device_name: str
    device_id: str
    version: str


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class PairingService:
    def __init__(self, host: str, port: int, pair_code_provider: Callable[[], str], device_info_provider: Callable[[], dict], on_start_client: Callable[[str, int, str], tuple[bool, str]], on_stop_client: Callable[[], None], on_status: Callable[[str], None] | None = None):
        self.host = host
        self.port = int(port)
        self.pair_code_provider = pair_code_provider
        self.device_info_provider = device_info_provider
        self.on_start_client = on_start_client
        self.on_stop_client = on_stop_client
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
                        raise ValueError
                    response = service._handle(req)
                except Exception as exc:
                    response = {"ok": False, "error": f"请求格式错误：{exc}"}
                self.wfile.write((json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        self._server = _ThreadingTCPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, name="pairing-service", daemon=True)
        self._thread.start()
        self.on_status(f"设备配对服务已启动 · {self.port}")

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None

    def _handle(self, req: dict) -> dict:
        action = req.get("action")
        if req.get("protocol") != PROTOCOL_VERSION:
            return {"ok": False, "error": "软件版本不兼容，请两台电脑安装相同最新版"}
        if action == "probe":
            return {"ok": True, **self.device_info_provider()}
        if action not in {"start_client", "stop_client"}:
            return {"ok": False, "error": "不支持的操作"}
        if not verify_payload(req, self.pair_code_provider()):
            return {"ok": False, "error": "配对码不正确，请重新复制第二台电脑的配对码"}
        if action == "stop_client":
            self.on_stop_client()
            return {"ok": True}
        server_ip = str(req.get("server_ip", "")).strip()
        client_name = str(req.get("client_name", "")).strip()
        try:
            server_port = int(req.get("server_port", 24861))
        except (TypeError, ValueError):
            return {"ok": False, "error": "服务端口无效"}
        ok, message = self.on_start_client(server_ip, server_port, client_name)
        return {"ok": ok, "message": message, "error": "" if ok else message}


class PairingClient:
    @staticmethod
    def _request(host: str, port: int, payload: dict, timeout: float = 4.0) -> dict:
        data = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with socket.create_connection((host, int(port)), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(data)
            file = sock.makefile("rb")
            raw = file.readline(MAX_LINE)
        if not raw:
            raise ConnectionError("第二台电脑没有返回数据")
        result = json.loads(raw.decode("utf-8"))
        if not isinstance(result, dict):
            raise ConnectionError("第二台电脑返回数据格式错误")
        return result

    @classmethod
    def probe(cls, host: str, port: int) -> ProbeInfo:
        payload = {"protocol": PROTOCOL_VERSION, "action": "probe", "nonce": secrets.token_hex(12)}
        result = cls._request(host, port, payload)
        if not result.get("ok"):
            raise ConnectionError(str(result.get("error", "无法识别第二台电脑")))
        return ProbeInfo(str(result.get("device_name", host)), str(result.get("device_id", "")), str(result.get("version", "")))

    @classmethod
    def start_remote_client(cls, host: str, port: int, pair_code: str, server_ip: str, server_port: int, client_name: str) -> dict:
        payload = {"protocol": PROTOCOL_VERSION, "action": "start_client", "timestamp": int(time.time()), "nonce": secrets.token_hex(16), "server_ip": server_ip, "server_port": int(server_port), "client_name": client_name}
        payload["proof"] = sign_payload(payload, pair_code)
        return cls._request(host, port, payload, timeout=7.0)

    @classmethod
    def stop_remote_client(cls, host: str, port: int, pair_code: str) -> None:
        payload = {"protocol": PROTOCOL_VERSION, "action": "stop_client", "timestamp": int(time.time()), "nonce": secrets.token_hex(16)}
        payload["proof"] = sign_payload(payload, pair_code)
        try:
            cls._request(host, port, payload, timeout=3.0)
        except Exception:
            pass

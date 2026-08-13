from __future__ import annotations

import select
import socket
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    error: str = ""
    winerror: int | None = None


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> ProbeResult:
    """Open a real TCP connection and close it immediately.

    This deliberately tests the same route that Deskflow will use.  It is used
    both for host readiness and for client preflight so the UI never reports
    "host ready" merely because a process happens to still be alive.
    """
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return ProbeResult(True)
    except OSError as exc:
        return ProbeResult(False, str(exc), getattr(exc, "winerror", None) or getattr(exc, "errno", None))


class TcpForwarder:
    """Small full-duplex TCP bridge owned by the ShifanAI app.

    Deskflow itself is kept on a loopback-only backend port.  The app owns the
    LAN-facing listener, which gives us deterministic binding, deterministic
    firewall rules and a listener that can be verified before the UI says the
    host is ready.
    """

    def __init__(
        self,
        listen_host: str,
        listen_port: int,
        backend_host: str,
        backend_port: int,
    ) -> None:
        self.listen_host = listen_host
        self.listen_port = int(listen_port)
        self.backend_host = backend_host
        self.backend_port = int(backend_port)
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._pairs: set[tuple[socket.socket, socket.socket]] = set()
        self._last_error = ""

    def start(self) -> tuple[bool, str]:
        self.stop()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.listen_host, self.listen_port))
            listener.listen(32)
            listener.settimeout(0.5)
        except OSError as exc:
            try:
                listener.close()
            finally:
                code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
                detail = f"（错误码 {code}）" if code else ""
                return False, f"无法监听 TCP {self.listen_port}{detail}：{exc}"

        self._stop.clear()
        self._listener = listener
        self._accept_thread = threading.Thread(target=self._accept_loop, name="shifan-lan-bridge", daemon=True)
        self._accept_thread.start()
        return True, f"0.0.0.0:{self.listen_port} -> {self.backend_host}:{self.backend_port}"

    def stop(self) -> None:
        self._stop.set()
        listener = self._listener
        self._listener = None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        with self._lock:
            pairs = list(self._pairs)
            self._pairs.clear()
        for left, right in pairs:
            for sock in (left, right):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass
        thread = self._accept_thread
        self._accept_thread = None
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.2)

    def _accept_loop(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stop.is_set():
            try:
                client, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def _handle_client(self, client: socket.socket) -> None:
        backend: socket.socket | None = None
        try:
            client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            backend = socket.create_connection((self.backend_host, self.backend_port), timeout=4.0)
            backend.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client.settimeout(None)
            backend.settimeout(None)
            pair = (client, backend)
            with self._lock:
                self._pairs.add(pair)

            while not self._stop.is_set():
                readable, _, exceptional = select.select([client, backend], [], [client, backend], 0.5)
                if exceptional:
                    break
                for source in readable:
                    target = backend if source is client else client
                    data = source.recv(65536)
                    if not data:
                        return
                    target.sendall(data)
        except OSError as exc:
            self._last_error = str(exc)
        finally:
            if backend is not None:
                with self._lock:
                    self._pairs.discard((client, backend))
            for sock in (client, backend):
                if sock is None:
                    continue
                try:
                    sock.close()
                except OSError:
                    pass

    def status(self) -> dict:
        with self._lock:
            active = len(self._pairs)
        return {
            "running": bool(self._listener is not None and not self._stop.is_set()),
            "listen": f"{self.listen_host}:{self.listen_port}",
            "backend": f"{self.backend_host}:{self.backend_port}",
            "active_connections": active,
            "last_error": self._last_error,
        }

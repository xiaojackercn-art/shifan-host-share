from __future__ import annotations

import select
import socket
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    error: str = ""
    winerror: int | None = None


def probe_tcp(host: str, port: int, timeout: float = 2.0) -> ProbeResult:
    """Open a real TCP connection and close it immediately."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return ProbeResult(True)
    except OSError as exc:
        return ProbeResult(False, str(exc), getattr(exc, "winerror", None) or getattr(exc, "errno", None))


def probe_tcp_until(
    host: str,
    port: int,
    *,
    total_timeout: float = 2.5,
    attempt_timeout: float = 0.35,
    cancel_event: threading.Event | None = None,
) -> ProbeResult:
    """Retry a TCP probe while remaining immediately cancellable.

    A single Windows TCP connect can otherwise keep the UI looking stuck for
    the whole socket timeout.  Short attempts plus a cancellation event keep
    the Stop/Cancel button responsive while still allowing a slow LAN adapter
    a few seconds to come up.
    """
    deadline = time.monotonic() + max(0.05, float(total_timeout))
    last = ProbeResult(False, "连接超时")
    while True:
        if cancel_event is not None and cancel_event.is_set():
            return ProbeResult(False, "操作已取消")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last
        last = probe_tcp(host, port, timeout=min(max(0.05, attempt_timeout), remaining))
        if last.ok:
            return last
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return last
        sleep_for = min(0.12, remaining)
        if cancel_event is not None:
            if cancel_event.wait(sleep_for):
                return ProbeResult(False, "操作已取消")
        else:
            time.sleep(sleep_for)


class TcpForwarder:
    """Small full-duplex TCP bridge owned by the ShifanAI app.

    Deskflow itself is kept on a loopback-only backend port.  The app owns the
    LAN-facing listener, which gives us deterministic binding and makes it
    possible to validate the transport independently of Deskflow's adapter
    selection.
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

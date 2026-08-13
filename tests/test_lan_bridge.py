from __future__ import annotations

import socket
import threading

from shifan_host_share.lan_bridge import TcpForwarder, probe_tcp


def _echo_connection(conn: socket.socket):
    with conn:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            conn.sendall(data)


def _echo_server(listener: socket.socket, stop: threading.Event):
    listener.settimeout(0.25)
    while not stop.is_set():
        try:
            conn, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=_echo_connection, args=(conn,), daemon=True).start()


def test_tcp_forwarder_moves_real_bytes_bidirectionally():
    backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend.bind(("127.0.0.1", 0))
    backend.listen(8)
    backend_port = backend.getsockname()[1]
    stop = threading.Event()
    threading.Thread(target=_echo_server, args=(backend, stop), daemon=True).start()

    public_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    public_probe.bind(("127.0.0.1", 0))
    public_port = public_probe.getsockname()[1]
    public_probe.close()

    bridge = TcpForwarder("127.0.0.1", public_port, "127.0.0.1", backend_port)
    ok, message = bridge.start()
    assert ok, message
    try:
        assert probe_tcp("127.0.0.1", public_port, 1.0).ok
        with socket.create_connection(("127.0.0.1", public_port), timeout=2.0) as client:
            client.sendall(b"shifan-host-share")
            assert client.recv(64) == b"shifan-host-share"
    finally:
        bridge.stop()
        stop.set()
        backend.close()

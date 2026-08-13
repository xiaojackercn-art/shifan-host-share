from __future__ import annotations

import socket
import threading

from shifan_host_share.lan_bridge import TcpForwarder, probe_tcp


def _echo_server(listener: socket.socket):
    conn, _ = listener.accept()
    with conn:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            conn.sendall(data)


def test_tcp_forwarder_moves_real_bytes_bidirectionally():
    backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    backend.bind(("127.0.0.1", 0))
    backend.listen(1)
    backend_port = backend.getsockname()[1]
    threading.Thread(target=_echo_server, args=(backend,), daemon=True).start()

    public_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    public_probe.bind(("127.0.0.1", 0))
    public_port = public_probe.getsockname()[1]
    public_probe.close()

    bridge = TcpForwarder("127.0.0.1", public_port, "127.0.0.1", backend_port)
    ok, message = bridge.start()
    assert ok, message
    try:
        assert probe_tcp("127.0.0.1", public_port, 1.0).ok
        # The first probe intentionally opens and closes one forwarded session;
        # start a fresh echo backend for the byte-level round trip.
        backend2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend2.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        backend.close()
        backend2.bind(("127.0.0.1", backend_port))
        backend2.listen(1)
        threading.Thread(target=_echo_server, args=(backend2,), daemon=True).start()
        with socket.create_connection(("127.0.0.1", public_port), timeout=2.0) as client:
            client.sendall(b"shifan-host-share")
            assert client.recv(64) == b"shifan-host-share"
        backend2.close()
    finally:
        bridge.stop()

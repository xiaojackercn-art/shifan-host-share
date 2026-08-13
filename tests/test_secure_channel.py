import socket
import threading

from shifan_host_share.secure_channel import SecureChannel, normalize_key


def test_normalize_key():
    assert normalize_key("abcd-ef12 34") == "ABCDEF1234"


def test_encrypted_roundtrip():
    a, b = socket.socketpair()
    ca = SecureChannel(a, "AAAA-BBBB", "CCCC-DDDD")
    cb = SecureChannel(b, "AAAA-BBBB", "CCCC-DDDD")
    payload = {"type": "move_rel", "dx": 12, "dy": -4, "text": "中文"}
    t = threading.Thread(target=lambda: ca.send(payload))
    t.start()
    assert cb.recv() == payload
    t.join()
    ca.close()
    cb.close()

import threading
import time

from shifan_host_share.lan_bridge import probe_tcp_until


def test_tcp_probe_can_be_cancelled_immediately():
    cancelled = threading.Event()
    cancelled.set()
    started = time.monotonic()
    result = probe_tcp_until("203.0.113.1", 24800, total_timeout=5.0, cancel_event=cancelled)
    elapsed = time.monotonic() - started
    assert not result.ok
    assert result.error == "操作已取消"
    assert elapsed < 0.5

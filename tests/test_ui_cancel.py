import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from shifan_host_share.app import MainWindow


class FakeApi:
    def __init__(self):
        self.status = {"kind": "ready", "text": "准备就绪", "detail": "", "role": "idle"}

    def get_state(self):
        return {
            "version": "0.9.0",
            "device": {
                "name": "TEST",
                "id": "12345678ABCD",
                "pair_code": "ABCD-EFGH-2345",
                "recommended_ip": "192.168.1.6",
                "addresses": [{"interface": "Ethernet", "ip": "192.168.1.6", "virtual": False}],
            },
            "peer": {},
            "engine": {"available": True, "version": "1.26.0"},
            "os": "Windows",
            "role": "idle",
        }

    def get_status(self):
        return dict(self.status)

    def connect(self, payload, cancel_event=None):
        self.status = {"kind": "connecting", "text": "正在连接", "detail": "", "role": "client"}
        while cancel_event is not None and not cancel_event.wait(0.01):
            pass
        return {"ok": False, "cancelled": True, "error": "操作已取消"}

    def prepare_host(self, cancel_event=None):
        return {"ok": False, "cancelled": True, "error": "操作已取消"}

    def disconnect(self):
        time.sleep(0.03)
        self.status = {"kind": "ready", "text": "共享已停止", "detail": "", "role": "idle"}
        return {"ok": True}

    def regenerate_code(self):
        return {"ok": True, "pair_code": "ABCD-EFGH-2345"}

    def close(self):
        return None


def _spin(app, predicate, timeout=1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_stop_during_connect_resets_ui_and_ignores_stale_worker():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(FakeApi())
    window._set_role("client", force=True)
    window.peer_ip.setText("192.168.1.4")
    window.peer_code.setText("ABCD-EFGH-2345")

    window._connect()
    assert window._busy
    assert window.stop_btn.text() == "取消连接"

    window._stop()
    assert not window._busy
    assert window._stopping
    assert window.connect_btn.text().startswith("连接主控电脑")

    assert _spin(app, lambda: not window._stopping)
    assert not window.stop_btn.isVisible()
    assert window.connect_btn.isEnabled()
    assert window.connect_btn.text().startswith("连接主控电脑")
    window.close()

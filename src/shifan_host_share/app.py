from __future__ import annotations

import platform
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .api import AppApi

APP_NAME = "视饭AI:主机共享"


class UiSignals(QObject):
    action_finished = Signal(dict)


def _asset_path(name: str) -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([exe_dir / "assets" / name, Path(getattr(sys, "_MEIPASS", exe_dir)) / "assets" / name])
        if platform.system() == "Darwin":
            try:
                candidates.append(Path(sys.executable).resolve().parents[1] / "Resources" / "assets" / name)
            except IndexError:
                pass
    root = Path(__file__).resolve().parents[2]
    candidates.extend([root / "assets" / name, Path(__file__).resolve().parent / "web" / name])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


class MainWindow(QMainWindow):
    def __init__(self, api: AppApi):
        super().__init__()
        self.api = api
        self.signals = UiSignals()
        self.signals.action_finished.connect(self._on_action_finished)
        self.direction = "right"
        self._busy = False
        self.role_mode = "host"

        self.setWindowTitle(APP_NAME)
        self.resize(1120, 760)
        self.setMinimumSize(980, 680)
        icon = _asset_path("AI.png")
        if icon:
            self.setWindowIcon(QIcon(str(icon)))
        self._build_ui()
        self._apply_style()
        self._load_state()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_status)
        self.timer.start(600)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(18)

        header = QHBoxLayout()
        logo = QLabel()
        logo.setFixedSize(54, 54)
        logo.setObjectName("logo")
        icon = _asset_path("AI.png")
        if icon:
            logo.setPixmap(QIcon(str(icon)).pixmap(54, 54))
        header.addWidget(logo)
        titles = QVBoxLayout()
        title = QLabel(APP_NAME)
        title.setObjectName("brandTitle")
        subtitle = QLabel("一套鼠标键盘 · Windows / macOS 无缝跨屏")
        subtitle.setObjectName("muted")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header.addLayout(titles)
        header.addStretch(1)
        self.top_status = QLabel("● 准备就绪")
        self.top_status.setObjectName("topStatus")
        header.addWidget(self.top_status)
        outer.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(18)
        row.addWidget(self._local_card(), 9)
        row.addWidget(self._role_card(), 11)
        outer.addLayout(row, 1)

        status = QFrame()
        status.setObjectName("statusCard")
        sl = QHBoxLayout(status)
        sl.setContentsMargins(18, 13, 18, 13)
        dot = QLabel("●")
        dot.setObjectName("statusDot")
        sl.addWidget(dot)
        texts = QVBoxLayout()
        self.status_text = QLabel("准备就绪")
        self.status_text.setObjectName("statusText")
        self.status_detail = QLabel("主控电脑启动后，第二台电脑直接连接 TCP 24800")
        self.status_detail.setObjectName("muted")
        self.status_detail.setWordWrap(True)
        texts.addWidget(self.status_text)
        texts.addWidget(self.status_detail)
        sl.addLayout(texts, 1)
        self.engine_text = QLabel("Deskflow Core · 检查中")
        self.engine_text.setObjectName("engineText")
        sl.addWidget(self.engine_text)
        outer.addWidget(status)

    def _card(self):
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        return frame, layout

    def _local_card(self):
        frame, layout = self._card()
        top = QHBoxLayout()
        labels = QVBoxLayout()
        eye = QLabel("THIS COMPUTER")
        eye.setObjectName("eyebrow")
        heading = QLabel("本机连接信息")
        heading.setObjectName("sectionTitle")
        labels.addWidget(eye)
        labels.addWidget(heading)
        top.addLayout(labels)
        top.addStretch(1)
        self.version_badge = QLabel("v--")
        self.version_badge.setObjectName("badge")
        top.addWidget(self.version_badge, 0, Qt.AlignTop)
        layout.addLayout(top)

        device = QFrame()
        device.setObjectName("innerPanel")
        drow = QHBoxLayout(device)
        mark = QLabel("⌘")
        mark.setAlignment(Qt.AlignCenter)
        mark.setObjectName("deviceMark")
        mark.setFixedSize(42, 42)
        drow.addWidget(mark)
        db = QVBoxLayout()
        self.device_name = QLabel("正在读取…")
        self.device_name.setObjectName("valueStrong")
        self.os_text = QLabel("本机")
        self.os_text.setObjectName("muted")
        db.addWidget(self.device_name)
        db.addWidget(self.os_text)
        drow.addLayout(db)
        drow.addStretch(1)
        ready = QLabel("● 可用")
        ready.setObjectName("readyPill")
        drow.addWidget(ready)
        layout.addWidget(device)

        layout.addWidget(self._info_box("推荐局域网 IP", "local_ip"))
        layout.addWidget(self._info_box("本机安全配对码", "pair_code", accent=True))
        self.lan_hint = QLabel("只显示物理局域网优先地址")
        self.lan_hint.setObjectName("hintPanel")
        self.lan_hint.setWordWrap(True)
        layout.addWidget(self.lan_hint)
        self.regen_btn = QPushButton("↻ 重新生成配对码")
        self.regen_btn.setObjectName("secondaryButton")
        self.regen_btn.clicked.connect(self._regenerate)
        layout.addWidget(self.regen_btn, 0, Qt.AlignLeft)
        layout.addStretch(1)
        return frame

    def _info_box(self, label_text: str, attr_name: str, accent: bool = False):
        panel = QFrame()
        panel.setObjectName("accentPanel" if accent else "innerPanel")
        box = QVBoxLayout(panel)
        label = QLabel(label_text)
        label.setObjectName("muted")
        box.addWidget(label)
        row = QHBoxLayout()
        value = QLabel("--")
        value.setObjectName("monoValue")
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        setattr(self, attr_name, value)
        row.addWidget(value, 1)
        copy = QPushButton("复制")
        copy.setObjectName("copyButton")
        copy.clicked.connect(lambda _=False, w=value: QApplication.clipboard().setText(w.text()))
        row.addWidget(copy)
        box.addLayout(row)
        return panel

    def _role_card(self):
        frame, layout = self._card()
        eye = QLabel("ROLE")
        eye.setObjectName("eyebrow")
        heading = QLabel("这台电脑是哪一台？")
        heading.setObjectName("sectionTitle")
        layout.addWidget(eye)
        layout.addWidget(heading)

        role_row = QHBoxLayout()
        self.host_tab = QPushButton("鼠标键盘在这台\n主控电脑")
        self.client_tab = QPushButton("另一块屏幕\n第二台电脑")
        for btn in (self.host_tab, self.client_tab):
            btn.setCheckable(True)
            btn.setObjectName("roleButton")
            role_row.addWidget(btn)
        self.host_tab.clicked.connect(lambda: self._set_role("host"))
        self.client_tab.clicked.connect(lambda: self._set_role("client"))
        layout.addLayout(role_row)

        self.role_stack = QStackedWidget()
        self.role_stack.addWidget(self._host_panel())
        self.role_stack.addWidget(self._client_panel())
        layout.addWidget(self.role_stack, 1)
        self.stop_btn = QPushButton("停止共享")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setVisible(False)
        layout.addWidget(self.stop_btn)
        return frame

    def _host_panel(self):
        panel = QWidget()
        l = QVBoxLayout(panel)
        l.setContentsMargins(0, 8, 0, 0)
        title = QLabel("主控电脑不需要填写任何内容")
        title.setObjectName("panelTitle")
        desc = QLabel("点击下面一个按钮即可。第二台电脑之后只输入这里显示的 IP 和配对码。")
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        l.addWidget(title)
        l.addWidget(desc)
        self.host_summary = QLabel("Deskflow 将直接监听 TCP 24800，不再使用 35999 配对端口。")
        self.host_summary.setObjectName("hintPanel")
        self.host_summary.setWordWrap(True)
        l.addWidget(self.host_summary)
        self.host_btn = QPushButton("启动主控模式   →")
        self.host_btn.setObjectName("primaryButton")
        self.host_btn.clicked.connect(self._start_host)
        l.addWidget(self.host_btn)
        l.addStretch(1)
        return panel

    def _client_panel(self):
        panel = QWidget()
        l = QVBoxLayout(panel)
        l.setContentsMargins(0, 8, 0, 0)
        l.addWidget(self._field_label("主控电脑 IP"))
        self.peer_ip = QLineEdit()
        self.peer_ip.setPlaceholderText("例如 192.168.1.6")
        self.peer_ip.setObjectName("input")
        l.addWidget(self.peer_ip)
        l.addWidget(self._field_label("主控电脑配对码"))
        self.peer_code = QLineEdit()
        self.peer_code.setPlaceholderText("例如 ABCD-EFGH-2345")
        self.peer_code.setObjectName("input")
        l.addWidget(self.peer_code)
        side = QHBoxLayout()
        side.addWidget(self._field_label("这块屏幕在主控电脑哪一边？"))
        side.addStretch(1)
        l.addLayout(side)
        dirs = QHBoxLayout()
        self.dir_group = QButtonGroup(self)
        self.dir_group.setExclusive(True)
        for key, text in [("left", "← 左边"), ("right", "→ 右边"), ("up", "↑ 上边"), ("down", "↓ 下边")]:
            b = QPushButton(text)
            b.setObjectName("directionButton")
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, k=key: self._select_direction(k))
            self.dir_group.addButton(b)
            dirs.addWidget(b)
            if key == "right":
                b.setChecked(True)
        l.addLayout(dirs)
        note = QLabel("只需要这 3 项。软件会直接使用 Deskflow 官方连接端口 24800。")
        note.setObjectName("muted")
        l.addWidget(note)
        self.connect_btn = QPushButton("连接主控电脑   →")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._connect)
        l.addWidget(self.connect_btn)
        l.addStretch(1)
        return panel

    def _field_label(self, text):
        lab = QLabel(text)
        lab.setObjectName("fieldLabel")
        return lab

    def _set_role(self, role: str):
        self.role_mode = role
        self.host_tab.setChecked(role == "host")
        self.client_tab.setChecked(role == "client")
        self.role_stack.setCurrentIndex(0 if role == "host" else 1)

    def _select_direction(self, direction: str):
        self.direction = direction
        for b in self.dir_group.buttons():
            text = b.text()
            b.setChecked((direction == "left" and "左" in text) or (direction == "right" and "右" in text) or (direction == "up" and "上" in text) or (direction == "down" and "下" in text))

    def _load_state(self):
        state = self.api.get_state()
        self.version_badge.setText(f"v{state['version']}")
        dev = state["device"]
        self.device_name.setText(dev["name"])
        self.os_text.setText(f"{state['os']} · 设备 ID {dev['id'][:8]}")
        self.local_ip.setText(dev["recommended_ip"])
        self.pair_code.setText(dev["pair_code"])
        physical = [a for a in dev.get("addresses", []) if not a.get("virtual")]
        self.lan_hint.setText("物理网卡 · " + "   ".join(f"{a['interface']} · {a['ip']}" for a in physical[:3]) if physical else "未检测到物理局域网 IPv4")
        peer = state.get("peer") or {}
        self.peer_ip.setText(peer.get("host", ""))
        self.peer_code.setText(peer.get("pair_code", ""))
        self._select_direction(peer.get("direction", "right"))
        eng = state.get("engine") or {}
        self.engine_text.setText(f"Deskflow Core {eng.get('version', '')} · {'已就绪' if eng.get('available') else '核心缺失'}")
        self._set_role("host")

    def _run_async(self, func):
        if self._busy:
            return
        self._busy = True
        self.host_btn.setEnabled(False)
        self.connect_btn.setEnabled(False)
        def work():
            try:
                result = func()
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self.signals.action_finished.emit(result)
        threading.Thread(target=work, daemon=True).start()

    def _start_host(self):
        self.host_btn.setText("正在启动 Deskflow…")
        self._run_async(self.api.prepare_host)

    def _connect(self):
        host = self.peer_ip.text().strip()
        code = self.peer_code.text().strip()
        if not host or not code:
            QMessageBox.warning(self, "信息未填完整", "请输入主控电脑 IP 和配对码。")
            return
        self.connect_btn.setText("正在连接主控电脑…")
        self._run_async(lambda: self.api.connect({"host": host, "pair_code": code, "direction": self.direction}))

    def _on_action_finished(self, result: dict):
        self._busy = False
        self.host_btn.setEnabled(True)
        self.connect_btn.setEnabled(True)
        self.host_btn.setText("启动主控模式   →")
        self.connect_btn.setText("连接主控电脑   →")
        if not result.get("ok"):
            QMessageBox.critical(self, "操作失败", str(result.get("error", "未知错误")))
        else:
            self.stop_btn.setVisible(True)

    def _regenerate(self):
        if QMessageBox.question(self, "重新生成配对码", "旧配对码会立即失效，是否继续？") == QMessageBox.Yes:
            result = self.api.regenerate_code()
            if result.get("ok"):
                self.pair_code.setText(result["pair_code"])

    def _stop(self):
        self.api.disconnect()
        self.stop_btn.setVisible(False)

    def _poll_status(self):
        try:
            s = self.api.get_status()
        except Exception:
            return
        self.status_text.setText(s.get("text", "准备就绪"))
        self.status_detail.setText(s.get("detail", ""))
        kind = s.get("kind")
        if kind == "connected":
            self.top_status.setText("● 已连接")
            self.stop_btn.setVisible(True)
        elif kind == "remote":
            self.top_status.setText("● 已连接主控")
            self.stop_btn.setVisible(True)
        elif kind == "host_waiting":
            self.top_status.setText("● 主控等待中")
            self.stop_btn.setVisible(True)
        elif kind == "connecting":
            self.top_status.setText("● 正在连接")
        elif kind == "error":
            self.top_status.setText("● 需要处理")
        else:
            self.top_status.setText("● 准备就绪")

    def _apply_style(self):
        self.setFont(QFont("Microsoft YaHei UI" if platform.system() == "Windows" else ".AppleSystemUIFont", 10))
        self.setStyleSheet("""
        QWidget#root { background:#07101d; color:#eef5ff; }
        QLabel#brandTitle { font-size:25px; font-weight:700; color:#f5f9ff; }
        QLabel#muted { color:#7890ad; font-size:12px; }
        QLabel#topStatus { color:#9fd8c0; background:#0e2238; border:1px solid #1d405f; border-radius:17px; padding:9px 14px; }
        QLabel#logo { border-radius:16px; background:#10233d; }
        QFrame#card { background:#0d1b2d; border:1px solid #173452; border-radius:20px; }
        QFrame#innerPanel { background:#091726; border:1px solid #183653; border-radius:12px; }
        QFrame#accentPanel { background:#0b2038; border:1px solid #285a92; border-radius:12px; }
        QLabel#eyebrow { color:#4d91f6; font-size:10px; font-weight:700; }
        QLabel#sectionTitle { font-size:20px; font-weight:700; }
        QLabel#badge { color:#6faeff; background:#0a192b; border:1px solid #1d405f; border-radius:8px; padding:6px 9px; }
        QLabel#deviceMark { background:#1d5cb4; border-radius:11px; font-size:21px; font-weight:700; }
        QLabel#valueStrong, QLabel#panelTitle { font-weight:700; font-size:14px; }
        QLabel#readyPill { color:#72dbaf; font-size:11px; }
        QLabel#monoValue { color:#f4f8ff; font-size:16px; font-family:Consolas, 'SF Mono', monospace; font-weight:600; }
        QLabel#hintPanel { color:#8aa4c1; background:#091522; border:1px solid #183653; border-radius:10px; padding:11px; }
        QLabel#fieldLabel { color:#b4c4d8; font-size:12px; font-weight:600; }
        QLineEdit#input { min-height:42px; background:#081624; border:1px solid #1e3c5d; border-radius:11px; padding:0 13px; color:#eef5ff; font-size:13px; }
        QLineEdit#input:focus { border:1px solid #3c83e8; }
        QPushButton { border:none; }
        QPushButton#copyButton { background:#132b47; color:#78b6ff; border-radius:8px; padding:6px 12px; }
        QPushButton#secondaryButton { background:#0a192a; color:#a9bad0; border:1px solid #234462; border-radius:9px; padding:9px 13px; }
        QPushButton#roleButton { min-height:62px; background:#081624; color:#839ab4; border:1px solid #1e3c5d; border-radius:12px; font-weight:650; }
        QPushButton#roleButton:checked { background:#173b6c; color:#e9f4ff; border:1px solid #3b84eb; }
        QPushButton#directionButton { min-height:42px; background:#081624; color:#7790ac; border:1px solid #1e3c5d; border-radius:10px; }
        QPushButton#directionButton:checked { background:#173b6c; color:#d6e9ff; border:1px solid #3b84eb; }
        QPushButton#primaryButton { min-height:50px; background:#2877e8; color:white; border-radius:12px; font-size:14px; font-weight:700; }
        QPushButton#primaryButton:hover { background:#3486f4; }
        QPushButton#primaryButton:disabled { background:#24466d; color:#7d95af; }
        QPushButton#dangerButton { min-height:38px; background:#29171f; color:#ff9eaa; border:1px solid #68404c; border-radius:10px; }
        QFrame#statusCard { background:#0b192b; border:1px solid #173956; border-radius:15px; }
        QLabel#statusDot { color:#4f9cff; font-size:20px; }
        QLabel#statusText { font-size:13px; font-weight:700; }
        QLabel#engineText { color:#627c99; font-size:11px; }
        QMessageBox { background:#101f31; }
        """)

    def closeEvent(self, event):  # noqa: N802
        try:
            self.timer.stop()
            self.api.close()
        finally:
            event.accept()


def run():
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName(APP_NAME)
    icon = _asset_path("AI.png")
    if icon:
        qt_app.setWindowIcon(QIcon(str(icon)))
    api = AppApi()
    window = MainWindow(api)
    window.show()
    raise SystemExit(qt_app.exec())

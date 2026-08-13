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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from .api import AppApi

APP_NAME = "视饭AI:主机共享"


class UiSignals(QObject):
    connect_finished = Signal(dict)


def _asset_path(name: str) -> Path | None:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            exe_dir / "assets" / name,
            Path(getattr(sys, "_MEIPASS", exe_dir)) / "assets" / name,
        ])
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
        self.signals.connect_finished.connect(self._on_connect_finished)
        self.direction = "right"
        self._busy = False

        self.setWindowTitle(APP_NAME)
        self.resize(1120, 748)
        self.setMinimumSize(980, 670)
        icon = _asset_path("AI.png")
        if icon:
            self.setWindowIcon(QIcon(str(icon)))

        self._build_ui()
        self._apply_style()
        self._load_state()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._poll_status)
        self.timer.start(700)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setFixedSize(54, 54)
        logo.setObjectName("logo")
        icon = _asset_path("AI.png")
        if icon:
            logo.setPixmap(QIcon(str(icon)).pixmap(54, 54))
        else:
            logo.setText("AI")
            logo.setAlignment(Qt.AlignCenter)
        header.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(3)
        title = QLabel(APP_NAME)
        title.setObjectName("brandTitle")
        subtitle = QLabel("一套鼠标键盘 · 无缝跨越 Windows 与 macOS")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch(1)
        self.top_status = QLabel("●  本机已就绪")
        self.top_status.setObjectName("topStatus")
        header.addWidget(self.top_status)
        outer.addLayout(header)

        cards = QHBoxLayout()
        cards.setSpacing(18)
        cards.addWidget(self._build_local_card(), 9)
        cards.addWidget(self._build_connect_card(), 11)
        outer.addLayout(cards, 1)

        status = QFrame()
        status.setObjectName("statusCard")
        status_layout = QHBoxLayout(status)
        status_layout.setContentsMargins(18, 13, 18, 13)
        status_layout.setSpacing(12)
        dot = QLabel("●")
        dot.setObjectName("statusDot")
        dot.setFixedWidth(22)
        status_layout.addWidget(dot)
        text_box = QVBoxLayout()
        text_box.setSpacing(2)
        self.status_text = QLabel("准备就绪 · 等待连接")
        self.status_text.setObjectName("statusText")
        self.status_detail = QLabel("两台电脑打开同一版本软件，输入第二台电脑 IP 和配对码即可")
        self.status_detail.setObjectName("muted")
        self.status_detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_box.addWidget(self.status_text)
        text_box.addWidget(self.status_detail)
        status_layout.addLayout(text_box, 1)
        self.engine_text = QLabel("Deskflow Core · 检查中")
        self.engine_text.setObjectName("engineText")
        status_layout.addWidget(self.engine_text)
        outer.addWidget(status)

    def _card(self) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        return frame, layout

    def _section_head(self, eyebrow: str, title: str, badge: str) -> tuple[QHBoxLayout, QLabel]:
        row = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(2)
        eye = QLabel(eyebrow)
        eye.setObjectName("eyebrow")
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        left.addWidget(eye)
        left.addWidget(heading)
        row.addLayout(left)
        row.addStretch(1)
        badge_label = QLabel(badge)
        badge_label.setObjectName("badge")
        row.addWidget(badge_label, 0, Qt.AlignTop)
        return row, badge_label

    def _build_local_card(self) -> QFrame:
        frame, layout = self._card()
        head, self.version_badge = self._section_head("THIS COMPUTER", "本机连接信息", "v--")
        layout.addLayout(head)

        device = QFrame()
        device.setObjectName("innerPanel")
        drow = QHBoxLayout(device)
        drow.setContentsMargins(14, 12, 14, 12)
        mark = QLabel("⌘")
        mark.setObjectName("deviceMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(42, 42)
        drow.addWidget(mark)
        db = QVBoxLayout()
        db.setSpacing(2)
        self.device_name = QLabel("正在读取…")
        self.device_name.setObjectName("valueStrong")
        self.os_text = QLabel("本机")
        self.os_text.setObjectName("muted")
        db.addWidget(self.device_name)
        db.addWidget(self.os_text)
        drow.addLayout(db)
        drow.addStretch(1)
        ready = QLabel("●  可被连接")
        ready.setObjectName("readyPill")
        drow.addWidget(ready)
        layout.addWidget(device)

        layout.addWidget(self._info_box("推荐局域网 IP", "local_ip", True))
        layout.addWidget(self._info_box("本机安全配对码", "pair_code", True, accent=True))

        self.lan_hint = QLabel("正在识别网卡…")
        self.lan_hint.setWordWrap(True)
        self.lan_hint.setObjectName("hintPanel")
        layout.addWidget(self.lan_hint)

        actions = QHBoxLayout()
        self.regen_btn = QPushButton("↻ 重新生成配对码")
        self.regen_btn.setObjectName("secondaryButton")
        self.regen_btn.clicked.connect(self._regenerate)
        actions.addWidget(self.regen_btn)
        self.permission_btn = QPushButton("系统输入权限")
        self.permission_btn.setObjectName("secondaryButton")
        self.permission_btn.clicked.connect(lambda: self.api.open_system_permissions())
        self.permission_btn.setVisible(platform.system() == "Darwin")
        actions.addWidget(self.permission_btn)
        actions.addStretch(1)
        layout.addLayout(actions)
        layout.addStretch(1)
        return frame

    def _info_box(self, label_text: str, attr_name: str, copy_button: bool, accent: bool = False) -> QFrame:
        panel = QFrame()
        panel.setObjectName("accentPanel" if accent else "innerPanel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 11, 14, 11)
        box.setSpacing(6)
        label = QLabel(label_text)
        label.setObjectName("muted")
        box.addWidget(label)
        row = QHBoxLayout()
        value = QLabel("--")
        value.setObjectName("monoValue")
        value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        setattr(self, attr_name, value)
        row.addWidget(value, 1)
        if copy_button:
            btn = QPushButton("复制")
            btn.setObjectName("copyButton")
            btn.clicked.connect(lambda _=False, widget=value: self._copy(widget.text()))
            row.addWidget(btn)
        box.addLayout(row)
        return panel

    def _build_connect_card(self) -> QFrame:
        frame, layout = self._card()
        head, _ = self._section_head("CONNECT", "连接第二台电脑", "◆ 本地安全配对")
        layout.addLayout(head)

        layout.addWidget(self._field_label("第二台电脑 IP"))
        self.peer_ip = QLineEdit()
        self.peer_ip.setPlaceholderText("例如 192.168.1.6")
        self.peer_ip.setObjectName("input")
        layout.addWidget(self.peer_ip)

        layout.addWidget(self._field_label("第二台电脑配对码"))
        self.peer_code = QLineEdit()
        self.peer_code.setPlaceholderText("例如 ABCD-EFGH-2345")
        self.peer_code.setObjectName("input")
        layout.addWidget(self.peer_code)

        pos_row = QHBoxLayout()
        pos_row.addWidget(self._field_label("第二台屏幕实际位置"))
        pos_row.addStretch(1)
        hint = QLabel("按你桌面真实摆放选择")
        hint.setObjectName("muted")
        pos_row.addWidget(hint)
        layout.addLayout(pos_row)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_group = QButtonGroup(self)
        self.dir_group.setExclusive(True)
        for key, text in [("left", "←  左侧"), ("right", "→  右侧"), ("up", "↑  上方"), ("down", "↓  下方")]:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setProperty("direction", True)
            btn.setObjectName("directionButton")
            btn.clicked.connect(lambda checked=False, k=key: self._select_direction(k))
            self.dir_group.addButton(btn)
            dir_row.addWidget(btn)
            if key == "right":
                btn.setChecked(True)
        layout.addLayout(dir_row)

        layout.addItem(QSpacerItem(10, 8, QSizePolicy.Minimum, QSizePolicy.Fixed))
        self.connect_btn = QPushButton("启动主机共享   →")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._connect)
        layout.addWidget(self.connect_btn)

        self.stop_btn = QPushButton("停止共享")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setVisible(False)
        layout.addWidget(self.stop_btn)
        layout.addStretch(1)
        return frame

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _apply_style(self) -> None:
        self.setFont(QFont("Microsoft YaHei UI" if platform.system() == "Windows" else ".AppleSystemUIFont", 10))
        self.setStyleSheet("""
        QWidget#root { background: #07101d; color: #eef5ff; }
        QLabel#brandTitle { font-size: 25px; font-weight: 700; color: #f5f9ff; }
        QLabel#muted { color: #7890ad; font-size: 12px; }
        QLabel#topStatus { color: #9fd8c0; background: #0e2238; border: 1px solid #1d405f; border-radius: 17px; padding: 9px 14px; }
        QLabel#logo { border-radius: 14px; background: #10233d; }
        QFrame#card { background: #0d1b2d; border: 1px solid #173452; border-radius: 20px; }
        QLabel#eyebrow { color: #4d91f6; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
        QLabel#sectionTitle { font-size: 20px; font-weight: 700; color: #eef5ff; }
        QLabel#badge { color: #6faeff; background: #0a192b; border: 1px solid #1d405f; border-radius: 8px; padding: 6px 9px; font-size: 11px; }
        QFrame#innerPanel { background: #091726; border: 1px solid #183653; border-radius: 12px; }
        QFrame#accentPanel { background: #0b2038; border: 1px solid #285a92; border-radius: 12px; }
        QLabel#deviceMark { background: #1d5cb4; border-radius: 11px; font-size: 21px; font-weight: 700; }
        QLabel#valueStrong { font-weight: 700; font-size: 14px; }
        QLabel#readyPill { color: #72dbaf; font-size: 11px; }
        QLabel#monoValue { color: #f4f8ff; font-size: 16px; font-family: Consolas, 'SF Mono', monospace; font-weight: 600; }
        QLabel#hintPanel { color: #718aa7; background: #091522; border: 1px solid #132e49; border-radius: 10px; padding: 10px; font-size: 11px; }
        QLabel#fieldLabel { color: #b4c4d8; font-size: 12px; font-weight: 600; margin-top: 2px; }
        QLineEdit#input { min-height: 42px; background: #081624; border: 1px solid #1e3c5d; border-radius: 11px; padding: 0 13px; color: #eef5ff; selection-background-color: #286fda; font-size: 13px; }
        QLineEdit#input:focus { border: 1px solid #3c83e8; }
        QPushButton { border: none; }
        QPushButton#copyButton { background: #132b47; color: #78b6ff; border-radius: 8px; padding: 6px 12px; }
        QPushButton#copyButton:hover { background: #19385c; }
        QPushButton#secondaryButton { background: #0a192a; color: #a9bad0; border: 1px solid #234462; border-radius: 9px; padding: 9px 13px; }
        QPushButton#secondaryButton:hover { border-color: #3e78b5; color: #e5f1ff; }
        QPushButton#directionButton { min-height: 43px; background: #081624; color: #7790ac; border: 1px solid #1e3c5d; border-radius: 10px; font-size: 12px; }
        QPushButton#directionButton:checked { background: #173b6c; color: #d6e9ff; border: 1px solid #3b84eb; }
        QPushButton#primaryButton { min-height: 48px; background: #2877e8; color: white; border-radius: 12px; font-size: 14px; font-weight: 700; }
        QPushButton#primaryButton:hover { background: #3486f4; }
        QPushButton#primaryButton:disabled { background: #24466d; color: #7d95af; }
        QPushButton#dangerButton { min-height: 38px; background: #29171f; color: #ff9eaa; border: 1px solid #68404c; border-radius: 10px; }
        QFrame#statusCard { background: #0b192b; border: 1px solid #173956; border-radius: 15px; }
        QLabel#statusDot { color: #4f9cff; font-size: 20px; }
        QLabel#statusText { color: #eef5ff; font-size: 13px; font-weight: 700; }
        QLabel#engineText { color: #627c99; font-size: 11px; }
        QMessageBox { background: #101f31; }
        """)

    def _load_state(self) -> None:
        state = self.api.get_state()
        self.version_badge.setText(f"v{state['version']}")
        device = state["device"]
        self.device_name.setText(device["name"])
        self.os_text.setText(f"{state['os']} · 设备 ID {device['id'][:8]}")
        self.local_ip.setText(device["recommended_ip"])
        self.pair_code.setText(device["pair_code"])
        addresses = device.get("addresses") or []
        if addresses:
            parts = []
            for item in addresses[:3]:
                prefix = "推荐" if item.get("recommended") else item.get("interface", "网卡")
                parts.append(f"{prefix} · {item['ip']}")
            self.lan_hint.setText("   ".join(parts))
        else:
            self.lan_hint.setText("未检测到局域网 IPv4；请确认 Wi-Fi 或网线已连接")
        peer = state.get("peer") or {}
        self.peer_ip.setText(peer.get("host", ""))
        self.peer_code.setText(peer.get("pair_code", ""))
        self._select_direction(peer.get("direction", "right"))
        engine = state.get("engine") or {}
        if engine.get("available"):
            self.engine_text.setText(f"Deskflow Core {engine.get('version', '')} · 已就绪")
        else:
            self.engine_text.setText("Deskflow Core · 核心缺失")
            self.engine_text.setStyleSheet("color:#ff7384")

    def _select_direction(self, direction: str) -> None:
        self.direction = direction if direction in {"left", "right", "up", "down"} else "right"
        for btn in self.dir_group.buttons():
            label = btn.text()
            match = ((self.direction == "left" and "左" in label) or
                     (self.direction == "right" and "右" in label) or
                     (self.direction == "up" and "上" in label) or
                     (self.direction == "down" and "下" in label))
            btn.setChecked(match)

    def _copy(self, text: str) -> None:
        QApplication.clipboard().setText(text)
        self.status_detail.setText("已复制到剪贴板")

    def _regenerate(self) -> None:
        reply = QMessageBox.question(self, "重新生成配对码", "旧配对码会立即失效，其他电脑需要重新复制。是否继续？")
        if reply == QMessageBox.Yes:
            result = self.api.regenerate_code()
            if result.get("ok"):
                self.pair_code.setText(result["pair_code"])

    def _connect(self) -> None:
        if self._busy:
            return
        host = self.peer_ip.text().strip()
        code = self.peer_code.text().strip()
        if not host:
            QMessageBox.warning(self, "缺少 IP", "请输入第二台电脑界面显示的局域网 IP。")
            self.peer_ip.setFocus()
            return
        if not code:
            QMessageBox.warning(self, "缺少配对码", "请输入第二台电脑界面显示的安全配对码。")
            self.peer_code.setFocus()
            return
        self._busy = True
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("正在建立连接…")
        payload = {"host": host, "pair_code": code, "direction": self.direction}

        def work() -> None:
            try:
                result = self.api.connect(payload)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self.signals.connect_finished.emit(result)

        threading.Thread(target=work, name="ui-connect", daemon=True).start()

    def _on_connect_finished(self, result: dict) -> None:
        self._busy = False
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("启动主机共享   →")
        if not result.get("ok"):
            QMessageBox.critical(self, "连接失败", str(result.get("error", "未知错误")))
        else:
            self.stop_btn.setVisible(True)

    def _stop(self) -> None:
        self.api.disconnect()
        self.stop_btn.setVisible(False)

    def _poll_status(self) -> None:
        try:
            status = self.api.get_status()
        except Exception:
            return
        kind = status.get("kind", "ready")
        self.status_text.setText(status.get("text") or "准备就绪")
        self.status_detail.setText(status.get("detail") or "")
        if kind == "connected":
            self.top_status.setText("●  共享运行中")
            self.top_status.setStyleSheet("color:#72dbaf")
            self.stop_btn.setVisible(True)
        elif kind == "remote":
            self.top_status.setText("●  正在被主控")
            self.top_status.setStyleSheet("color:#72dbaf")
        elif kind == "error":
            self.top_status.setText("●  需要处理")
            self.top_status.setStyleSheet("color:#ff8391")
        elif kind == "connecting":
            self.top_status.setText("●  正在连接")
            self.top_status.setStyleSheet("color:#76b7ff")
            self.stop_btn.setVisible(True)
        else:
            self.top_status.setText("●  本机已就绪")
            self.top_status.setStyleSheet("")

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.timer.stop()
            self.api.close()
        finally:
            event.accept()


def run() -> None:
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName(APP_NAME)
    qt_app.setOrganizationName("视饭AI")
    icon = _asset_path("AI.png")
    if icon:
        qt_app.setWindowIcon(QIcon(str(icon)))
    api = AppApi()
    window = MainWindow(api)
    window.show()
    raise SystemExit(qt_app.exec())

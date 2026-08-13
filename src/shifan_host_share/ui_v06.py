from __future__ import annotations

import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QSpacerItem, QVBoxLayout

from .app import MainWindow as BaseMainWindow


class MainWindowV06(BaseMainWindow):
    """v0.6 role-oriented UI.

    Host computer: click the host button and wait.
    Secondary computer: enter host IP + host pair code, choose physical screen
    position, and connect. This matches Deskflow's native server/client model.
    """

    def _build_connect_card(self) -> QFrame:
        frame, layout = self._card()
        head, _ = self._section_head("ROLE", "选择本机角色", "◆ Deskflow 标准连接模型")
        layout.addLayout(head)

        self.host_btn = QPushButton("① 将本机设为主控电脑")
        self.host_btn.setObjectName("primaryButton")
        self.host_btn.clicked.connect(self._prepare_host)
        layout.addWidget(self.host_btn)

        host_hint = self._field_label("主控电脑只需点击上方按钮并保持软件打开；第二台电脑主动连接主控。")
        host_hint.setWordWrap(True)
        host_hint.setObjectName("muted")
        layout.addWidget(host_hint)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("divider")
        layout.addWidget(divider)

        layout.addWidget(self._field_label("② 第二台电脑：输入主控电脑 IP"))
        self.peer_ip = QLineEdit()
        self.peer_ip.setPlaceholderText("例如 192.168.1.6")
        self.peer_ip.setObjectName("input")
        layout.addWidget(self.peer_ip)

        layout.addWidget(self._field_label("主控电脑配对码"))
        self.peer_code = QLineEdit()
        self.peer_code.setPlaceholderText("例如 ABCD-EFGH-2345")
        self.peer_code.setObjectName("input")
        layout.addWidget(self.peer_code)

        pos_row = QHBoxLayout()
        pos_row.addWidget(self._field_label("本机屏幕在主控电脑的哪个方向"))
        pos_row.addStretch(1)
        hint = self._field_label("按桌面真实摆放选择")
        hint.setObjectName("muted")
        pos_row.addWidget(hint)
        layout.addLayout(pos_row)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self.dir_group = QButtonGroup(self)
        self.dir_group.setExclusive(True)
        for key, text in [("left", "← 左侧"), ("right", "→ 右侧"), ("up", "↑ 上方"), ("down", "↓ 下方")]:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setObjectName("directionButton")
            btn.clicked.connect(lambda checked=False, k=key: self._select_direction(k))
            self.dir_group.addButton(btn)
            dir_row.addWidget(btn)
            if key == "right":
                btn.setChecked(True)
        layout.addLayout(dir_row)

        layout.addItem(QSpacerItem(10, 6, QSizePolicy.Minimum, QSizePolicy.Fixed))
        self.connect_btn = QPushButton("连接主控电脑   →")
        self.connect_btn.setObjectName("primaryButton")
        self.connect_btn.clicked.connect(self._connect)
        layout.addWidget(self.connect_btn)

        self.diag_btn = QPushButton("网络自检")
        self.diag_btn.setObjectName("secondaryButton")
        self.diag_btn.clicked.connect(self._diagnose)
        layout.addWidget(self.diag_btn)

        self.stop_btn = QPushButton("停止共享")
        self.stop_btn.setObjectName("dangerButton")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setVisible(False)
        layout.addWidget(self.stop_btn)
        layout.addStretch(1)
        return frame

    def _prepare_host(self) -> None:
        result = self.api.prepare_host()
        if not result.get("ok"):
            QMessageBox.critical(self, "主控启动失败", str(result.get("error") or "未知错误"))
            return
        self.stop_btn.setVisible(True)
        self.host_btn.setText("✓ 本机已作为主控 · 等待第二台电脑")
        self.status_text.setText("主控模式已开启")
        self.status_detail.setText(
            f"第二台电脑输入 {result.get('host_ip')} 和本机配对码，然后在第二台电脑点击“连接主控电脑”"
        )

    def _connect(self) -> None:
        if self._busy:
            return
        host = self.peer_ip.text().strip()
        code = self.peer_code.text().strip()
        if not host:
            QMessageBox.warning(self, "缺少主控 IP", "这里输入的是主控电脑左侧显示的局域网 IP。")
            self.peer_ip.setFocus()
            return
        if not code:
            QMessageBox.warning(self, "缺少配对码", "请输入主控电脑左侧显示的配对码。")
            self.peer_code.setFocus()
            return
        self._busy = True
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("正在连接主控电脑…")
        payload = {"host": host, "pair_code": code, "direction": self.direction}

        def work() -> None:
            try:
                result = self.api.connect(payload)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self.signals.connect_finished.emit(result)

        threading.Thread(target=work, name="ui-connect-v06", daemon=True).start()

    def _on_connect_finished(self, result: dict) -> None:
        self._busy = False
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("连接主控电脑   →")
        if not result.get("ok"):
            QMessageBox.critical(self, "连接失败", str(result.get("error", "未知错误")))
        else:
            self.stop_btn.setVisible(True)

    def _diagnose(self) -> None:
        host = self.peer_ip.text().strip()
        if not host:
            QMessageBox.information(self, "网络自检", "先输入主控电脑 IP，再点击网络自检。")
            return
        result = self.api.diagnose_host(host)
        title = "网络自检通过" if result.get("ok") else "网络自检失败"
        if result.get("ok"):
            QMessageBox.information(self, title, str(result.get("text") or ""))
        else:
            QMessageBox.warning(self, title, str(result.get("text") or ""))

    def _load_state(self) -> None:
        super()._load_state()
        state = self.api.get_state()
        # v0.6 intentionally does not present virtual adapters as recommended.
        physical = [x for x in state["device"].get("addresses", []) if not x.get("virtual")]
        if physical:
            self.lan_hint.setText("   ".join(f"物理网卡 · {x['interface']} · {x['ip']}" for x in physical[:3]))
        else:
            self.lan_hint.setText("未检测到物理局域网 IPv4；请确认 Wi-Fi 或网线已连接")
        peer = state.get("peer") or {}
        self.peer_ip.setText(peer.get("host", ""))
        self.peer_code.setText(peer.get("pair_code", ""))

    def _poll_status(self) -> None:
        super()._poll_status()
        try:
            status = self.api.get_status()
        except Exception:
            return
        role = status.get("role")
        if role == "host" and status.get("kind") not in {"connected", "error"}:
            self.top_status.setText("● 主控等待中")
            self.stop_btn.setVisible(True)
        elif role == "client" and status.get("kind") not in {"remote", "error"}:
            self.top_status.setText("● 正在连接主控")
            self.stop_btn.setVisible(True)


def install_v06_ui(app_module) -> None:
    app_module.MainWindow = MainWindowV06

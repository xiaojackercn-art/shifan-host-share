from __future__ import annotations

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from .config import format_pair_code_input


class PairAwareLineEdit(QtWidgets.QLineEdit):
    """QLineEdit that turns itself into a pairing-code editor when the app
    assigns the pairing-code placeholder. Other QLineEdit instances remain
    ordinary IP/text inputs.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pair_mode = False

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802
        super().setPlaceholderText(text)
        if not self._pair_mode and "ABCD-EFGH" in str(text).upper():
            self._pair_mode = True
            self.setMaxLength(14)
            self.textEdited.connect(self._format_pair_text)

    def _format_pair_text(self, text: str) -> None:
        formatted = format_pair_code_input(text)
        if formatted == text:
            return
        self.setText(formatted)
        self.setCursorPosition(len(formatted))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._pair_mode and event.key() == Qt.Key_Backspace:
            pos = self.cursorPosition()
            text = self.text()
            if pos > 0 and pos <= len(text) and text[pos - 1:pos] == "-":
                self.setCursorPosition(pos - 1)
        super().keyPressEvent(event)


def install_pair_code_editor() -> None:
    # app.py imports QLineEdit directly from QtWidgets. Install this subclass
    # before app.py is imported so only the pairing input activates its special
    # behavior via the pairing placeholder.
    QtWidgets.QLineEdit = PairAwareLineEdit

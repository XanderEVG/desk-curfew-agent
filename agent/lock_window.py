import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor


class LockWindow(QMainWindow):
    def __init__(self, reason=""):
        super().__init__()
        self.reason = reason
        self._setup_ui()
        self._setup_flags()

    def _setup_ui(self):
        self.setWindowTitle("Компьютер заблокирован")
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("🔒 Компьютер заблокирован")
        title.setFont(QFont("Segoe UI", 36, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: white;")
        layout.addWidget(title)

        reason_text = {
            "schedule": "Время работы закончилось",
            "daily_limit": "Дневной лимит времени исчерпан",
            "manual": "Заблокировано вручную",
        }.get(self.reason, "Доступ ограничен")

        reason_label = QLabel(reason_text)
        reason_label.setFont(QFont("Segoe UI", 18))
        reason_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        reason_label.setStyleSheet("color: #cccccc;")
        layout.addWidget(reason_label)

        hint = QLabel("Обратись к родителям для разблокировки")
        hint.setFont(QFont("Segoe UI", 14))
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #888888;")
        layout.addWidget(hint)

        self.setCentralWidget(central)

        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        self.setPalette(palette)
        self.setStyleSheet("background-color: #1e1e1e;")

    def _setup_flags(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )

    def show_fullscreen(self):
        self.showFullScreen()
        self.activateWindow()
        self.raise_()

    def closeEvent(self, event):
        event.ignore()

    def keyPressEvent(self, event):
        # Игнорируем попытки закрыть или свернуть через клавиатуру
        event.ignore()

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self.show_fullscreen)
        super().changeEvent(event)
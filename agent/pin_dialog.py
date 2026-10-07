"""PIN-пад для аварийного доступа (Ctrl+Alt+Shift+F12).

Topmost-окно с цифровым вводом. При верном PIN — меню
«Разблокировать / Закрыть агент / Отмена». При неверном — тихо закрывается
и отправляет event ``pin_attempt``.

Если ``pin_hash`` в конфиге пуст — при первом запуске предлагает создать PIN.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

log = logging.getLogger(__name__)

_WIN = sys.platform == "win32"

if _WIN:
    import ctypes
    import ctypes.wintypes


def hash_pin(pin: str) -> str:
    """Хешировать PIN (SHA-256)."""
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_pin(pin: str, pin_hash: str) -> bool:
    """Проверить PIN against hash."""
    return hash_pin(pin) == pin_hash


class PinDialog(QDialog):
    """PIN-пад для аварийного доступа.

    Параметры:
        pin_hash: хеш PIN из конфига (пуст = создать новый).
        on_unlock: callback при верном PIN + выборе «Разблокировать».
        on_close_agent: callback при верном PIN + выборе «Закрыть агент».
        on_wrong_pin: callback при неверном PIN (event pin_attempt).
    """

    def __init__(
        self,
        pin_hash: str,
        on_unlock: Callable[[], None] | None = None,
        on_close_agent: Callable[[], None] | None = None,
        on_wrong_pin: Callable[[], None] | None = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._pin_hash = pin_hash
        self._on_unlock = on_unlock
        self._on_close_agent = on_close_agent
        self._on_wrong_pin = on_wrong_pin

        self._setup_window()
        self._setup_ui()

    def _setup_window(self) -> None:
        """Topmost, без рамки, по центру экрана."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setFixedSize(400, 300)
        self.setStyleSheet("""
            PinDialog {
                background-color: #1e1e1e;
                border: 2px solid #444;
                border-radius: 12px;
            }
            QLabel {
                color: #f0f0f0;
                background: transparent;
            }
            QLineEdit {
                background-color: #2d2d2d;
                color: #f0f0f0;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 8px;
                font-size: 18px;
            }
            QPushButton {
                background-color: #3d3d3d;
                color: #f0f0f0;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
            }
        """)

        if _WIN:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)

        # Центрирование
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2
            y = (geo.height() - self.height()) // 2
            self.move(geo.x() + x, geo.y() + y)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(15)

        if not self._pin_hash:
            # Первый запуск — создание PIN
            title = QLabel("Создайте PIN-код")
            title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

            hint = QLabel("Этот PIN используется для аварийного доступа\n(Ctrl+Alt+Shift+F12)")
            hint.setFont(QFont("Segoe UI", 11))
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            hint.setStyleSheet("color: rgba(255,255,255,0.6);")
            layout.addWidget(hint)

            self._pin_input = QLineEdit()
            self._pin_input.setPlaceholderText("Введите PIN (4-8 цифр)")
            self._pin_input.setEchoMode(QLineEdit.EchoMode.Password)
            self._pin_input.setMaxLength(8)
            layout.addWidget(self._pin_input)

            confirm_btn = QPushButton("Создать PIN")
            confirm_btn.clicked.connect(self._create_pin)
            layout.addWidget(confirm_btn)
        else:
            # Ввод PIN
            title = QLabel("Введите PIN")
            title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(title)

            self._pin_input = QLineEdit()
            self._pin_input.setPlaceholderText("PIN")
            self._pin_input.setEchoMode(QLineEdit.EchoMode.Password)
            self._pin_input.setMaxLength(8)
            self._pin_input.returnPressed.connect(self._check_pin)
            layout.addWidget(self._pin_input)

            submit_btn = QPushButton("Войти")
            submit_btn.clicked.connect(self._check_pin)
            layout.addWidget(submit_btn)

            cancel_btn = QPushButton("Отмена")
            cancel_btn.clicked.connect(self.hide)
            layout.addWidget(cancel_btn)

        layout.addStretch()

    def _create_pin(self) -> None:
        """Создать новый PIN (первый запуск)."""
        pin = self._pin_input.text().strip()
        if not pin.isdigit() or not (4 <= len(pin) <= 8):
            QMessageBox.warning(self, "Ошибка", "PIN должен содержать 4-8 цифр")
            return

        # Сохраняем хеш в конфиг (вызов callback)
        new_hash = hash_pin(pin)
        log.info("PIN создан (hash=%s...)", new_hash[:8])

        # Обновляем config.ini
        self._save_pin_hash(new_hash)

        # После создания — показать меню
        self._pin_hash = new_hash
        self._show_menu()

    def _save_pin_hash(self, pin_hash: str) -> None:
        """Сохранить хеш PIN в config.ini."""
        import configparser
        from pathlib import Path

        exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        config_path = exe_dir / "config.ini"

        if not config_path.is_file():
            log.error("config.ini не найден — не могу сохранить PIN")
            return

        cp = configparser.ConfigParser()
        cp.read(config_path, encoding="utf-8")

        if not cp.has_section("security"):
            cp.add_section("security")
        cp.set("security", "pin_hash", pin_hash)

        with open(config_path, "w", encoding="utf-8") as f:
            cp.write(f)

        log.info("PIN сохранён в config.ini")

    def _check_pin(self) -> None:
        """Проверить введённый PIN."""
        pin = self._pin_input.text().strip()
        if verify_pin(pin, self._pin_hash):
            log.info("PIN верный — показываю меню")
            self._show_menu()
        else:
            log.warning("PIN неверный — event pin_attempt")
            if self._on_wrong_pin:
                self._on_wrong_pin()
            self.hide()

    def _show_menu(self) -> None:
        """Показать меню после верного PIN."""
        self._pin_input.clear()

        # Очищаем layout и показываем меню
        layout = self.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

        title = QLabel("Меню")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(20)

        unlock_btn = QPushButton("🔓 Разблокировать")
        unlock_btn.clicked.connect(self._do_unlock)
        layout.addWidget(unlock_btn)

        close_btn = QPushButton("❌ Закрыть агент")
        close_btn.clicked.connect(self._do_close_agent)
        layout.addWidget(close_btn)

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.hide)
        layout.addWidget(cancel_btn)

        layout.addStretch()

    def _do_unlock(self) -> None:
        log.info("Меню: Разблокировать")
        self.hide()
        if self._on_unlock:
            self._on_unlock()

    def _do_close_agent(self) -> None:
        log.info("Меню: Закрыть агент")
        self.hide()
        if self._on_close_agent:
            self._on_close_agent()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Esc — закрыть."""
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

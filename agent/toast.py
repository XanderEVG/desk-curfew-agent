"""Тосты уведомлений: lock_in отсчёт, +N минут, Разблокировано.

Topmost-окна в правом нижнем углу, не крадут фокус (WS_EX_NOACTIVATE).
На Linux (разработка) — обычные QWidget-тосты без Win-флагов.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

log = logging.getLogger(__name__)

_WIN = sys.platform == "win32"

if _WIN:
    import ctypes
    import ctypes.wintypes


class Toast(QWidget):
    """Небольшое всплывающее уведомление в правом нижнем углу.

    Параметры:
        text: текст тоста.
        duration_ms: авто-скрытие через N мс (0 = не скрывать автоматически).
        on_click: callback при клике (опционально).
    """

    def __init__(
        self,
        text: str,
        duration_ms: int = 5000,
        on_click: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._duration_ms = duration_ms
        self._on_click = on_click

        self._setup_ui(text)
        self._setup_window_flags()
        self._position_bottom_right()

        if duration_ms > 0:
            QTimer.singleShot(duration_ms, self.hide)

    def _setup_ui(self, text: str) -> None:
        self.setFixedWidth(360)
        self.setMinimumHeight(60)

        # Стилизуем под тёмный тост
        self.setStyleSheet("""
            Toast {
                background-color: rgba(30, 30, 30, 230);
                border: 1px solid rgba(80, 80, 80, 200);
                border-radius: 8px;
            }
            QLabel {
                color: #f0f0f0;
                font-size: 14px;
                padding: 12px;
                background: transparent;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)

        self._label = QLabel(text)
        self._label.setWordWrap(True)
        self._label.setFont(QFont("Segoe UI", 11))
        layout.addWidget(self._label)

        if self._on_click:
            btn = QPushButton("OK")
            btn.setFixedSize(50, 30)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: rgba(60, 60, 60, 200);
                    color: #f0f0f0;
                    border: 1px solid rgba(100, 100, 100, 200);
                    border-radius: 4px;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: rgba(80, 80, 80, 230);
                }
            """)
            btn.clicked.connect(self._on_click)
            btn.clicked.connect(self.hide)
            layout.addWidget(btn)

    def _setup_window_flags(self) -> None:
        """Окно поверх всех, скрыто из таскбара, не крадёт фокус."""
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.FramelessWindowHint
        )
        if _WIN:
            # WS_EX_NOACTIVATE — не красть фокус
            # WS_EX_TOOLWINDOW — скрыт из Alt+Tab / таскбара
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)

        # Прозрачный фон
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def _position_bottom_right(self) -> None:
        """Разместить в правом нижнем углу экрана."""
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.right() - self.width() - 20
            y = geo.bottom() - self.height() - 20
            self.move(x, y)

    def update_text(self, text: str) -> None:
        """Обновить текст тоста (для обратного отсчёта)."""
        self._label.setText(text)

    def mousePressEvent(self, event: Any) -> None:
        """Клик по тосту — скрыть."""
        self.hide()
        super().mousePressEvent(event)


class ToastManager:
    """Управление очередью тостов.

    Показывает тосты по одному (следующий появляется после скрытия предыдущего).
    """

    def __init__(self) -> None:
        self._current_toast: Toast | None = None
        self._queue: list[tuple[str, int]] = []  # (text, duration_ms)
        self._check_timer = QTimer()
        self._check_timer.timeout.connect(self._show_next)
        self._check_timer.start(500)

    def show(self, text: str, duration_ms: int = 5000) -> None:
        """Поставить тост в очередь."""
        log.info("Toast: %s", text)
        self._queue.append((text, duration_ms))
        # Если сейчас ничего не показывается — показать сразу
        if self._current_toast is None or not self._current_toast.isVisible():
            self._show_next()

    def _show_next(self) -> None:
        if self._current_toast and self._current_toast.isVisible():
            return
        if not self._queue:
            return

        text, duration_ms = self._queue.pop(0)
        self._current_toast = Toast(text, duration_ms)
        self._current_toast.show()
        log.debug("Toast shown: %s", text)

    def stop(self) -> None:
        self._check_timer.stop()
        if self._current_toast:
            self._current_toast.hide()


class LockInToast:
    """Тост с обратным отсчётом для команды lock_in.

    Показывает "⏰ Через N секунд компьютер заблокируется — сохрани прогресс",
    обновляет каждую секунду. По истечении вызывает callback.
    """

    def __init__(self, delay_seconds: int, on_expire: Any) -> None:
        self._remaining = delay_seconds
        self._on_expire = on_expire
        self._toast = Toast(self._format_text(), duration_ms=0)  # не авто-скрывается
        self._toast.show()

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

        log.info("LockInToast: обратный отсчёт %d с", delay_seconds)

    def _format_text(self) -> str:
        mins, secs = divmod(self._remaining, 60)
        if mins > 0:
            return f"⏰ Через {mins} мин {secs} сек компьютер заблокируется — сохрани прогресс"
        return f"⏰ Через {secs} сек компьютер заблокируется — сохрани прогресс"

    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self.cancel()
            self._on_expire()
            return
        self._toast.update_text(self._format_text())

    def cancel(self) -> None:
        """Отменить таймер и скрыть тост."""
        self._timer.stop()
        self._toast.hide()
        log.debug("LockInToast: отменён/истёк")

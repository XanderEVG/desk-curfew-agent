"""Экран блокировки в стиле BSOD (Windows 10/11).

Полноэкранный, без рамки, topmost, поверх таскбара.
Скрыт из Alt+Tab (WS_EX_TOOLWINDOW), игнорирует Alt+F4 / WM_CLOSE.
Контент рисуется из блока ``info``, который присылает сервер.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeyEvent, QCloseEvent
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

log = logging.getLogger(__name__)

_WIN = sys.platform == "win32"

if _WIN:
    import ctypes
    import ctypes.wintypes


# Стоп-коды по причинам
_REASON_STOP_CODES = {
    "daily_limit": "CURFEW_DAILY_LIMIT",
    "schedule": "CURFEW_SCHEDULE",
    "manual": "CURFEW_MANUAL",
}


class LockScreen(QWidget):
    """Полноэкранный экран блокировки в стиле BSOD.

    Параметры:
        info: блок ``info`` из команды сервера (опционален).
        reason: причина блокировки (daily_limit / schedule / manual).
    """

    def __init__(self, info: dict[str, Any] | None = None, reason: str = "manual") -> None:
        super().__init__()
        self._info = info or {}
        self._reason = reason

        self._setup_window()
        self._setup_ui()
        self._update_clock()

        # Обновление часов каждую секунду
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(1000)

    def _setup_window(self) -> None:
        """Полноэкранное окно без рамки, topmost, скрыто из таскбара."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool  # скрыт из Alt+Tab / таскбара
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        # Чёрный фон
        self.setStyleSheet("LockScreen { background-color: #0078d7; }")

        if _WIN:
            # WS_EX_TOOLWINDOW — скрыт из Alt+Tab и таскбара
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)

    def _setup_ui(self) -> None:
        """Построить содержимое экрана."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 60, 80, 60)
        layout.setSpacing(12)

        # :( — грустный смайлик
        sad_face = QLabel(":(")
        sad_face.setFont(QFont("Segoe UI Light", 140))
        sad_face.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(sad_face)
        layout.addSpacing(20)

        # reason_ru — основной текст
        reason_ru = self._info.get("reason_ru", self._default_reason_text())
        reason_label = QLabel(reason_ru)
        reason_label.setFont(QFont("Segoe UI", 22))
        reason_label.setWordWrap(True)
        reason_label.setStyleSheet("color: white; background: transparent;")
        layout.addWidget(reason_label)
        layout.addSpacing(10)

        # display_name
        display_name = self._info.get("display_name", "")
        if display_name:
            name_label = QLabel(display_name)
            name_label.setFont(QFont("Segoe UI", 14))
            name_label.setStyleSheet("color: rgba(255,255,255,0.8); background: transparent;")
            layout.addWidget(name_label)

        layout.addSpacing(20)

        # Информация о разблокировке
        unlock_info = self._format_unlock_info()
        if unlock_info:
            unlock_label = QLabel(unlock_info)
            unlock_label.setFont(QFont("Segoe UI", 16))
            unlock_label.setWordWrap(True)
            unlock_label.setStyleSheet("color: white; background: transparent;")
            layout.addWidget(unlock_label)

        # Текущее время и дата (обновляется)
        self._clock_label = QLabel()
        self._clock_label.setFont(QFont("Segoe UI", 14))
        self._clock_label.setStyleSheet("color: rgba(255,255,255,0.7); background: transparent;")
        layout.addWidget(self._clock_label)
        self._update_clock()

        layout.addStretch()

        # Подсказка
        hint = QLabel("Если это кажется ошибкой — попроси родителей добавить времени 🙂")
        hint.setFont(QFont("Segoe UI", 12))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: rgba(255,255,255,0.6); background: transparent;")
        layout.addWidget(hint)
        layout.addSpacing(20)

        # Стоп-код
        stop_code = _REASON_STOP_CODES.get(self._reason, "CURFEW_UNKNOWN")
        stop_label = QLabel(f"Stop code: {stop_code}")
        stop_label.setFont(QFont("Consolas", 11))
        stop_label.setStyleSheet("color: rgba(255,255,255,0.5); background: transparent;")
        layout.addWidget(stop_label)

    def _default_reason_text(self) -> str:
        """Текст по умолчанию, если info нет."""
        defaults = {
            "daily_limit": "Время за компьютером на сегодня закончилось",
            "schedule": "Сейчас по расписанию — перерыв",
            "manual": "Компьютер заблокирован родителем",
        }
        return defaults.get(self._reason, "Компьютер заблокирован")

    def _format_unlock_info(self) -> str:
        """Сформировать текст о разблокировке."""
        unlocks_at = self._info.get("unlocks_at")
        next_window = self._info.get("next_window")

        parts = []
        if unlocks_at:
            parts.append(f"Разблокировка: {self._format_time(unlocks_at)}")
        if next_window:
            parts.append(f"Следующее окно: {next_window}")
        if not parts:
            if self._reason == "daily_limit":
                parts.append("Разблокировка: завтра")
            elif self._reason == "manual":
                parts.append("Разблокировка: по решению родителя")

        return "\n".join(parts)

    def _format_time(self, iso_str: str) -> str:
        """Форматировать ISO-время в читаемый вид."""
        try:
            dt = datetime.fromisoformat(iso_str)
            return dt.strftime("%H:%M %d.%m.%Y")
        except (ValueError, TypeError):
            return iso_str

    def _update_clock(self) -> None:
        """Обновить текущее время и дату."""
        now = datetime.now()
        day_names = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        day_name = day_names[now.weekday()]
        self._clock_label.setText(
            f"{now.strftime('%H:%M:%S')}  •  {now.strftime('%d.%m.%Y')}  •  {day_name}"
        )

    def show_fullscreen(self) -> None:
        """Показать экран на весь экран."""
        self.showFullScreen()
        self.activateWindow()
        self.raise_()
        log.info("LockScreen: показан полноэкранно")

    def hide_lock(self) -> None:
        """Скрыть экран блокировки."""
        self._clock_timer.stop()
        self.hide()
        self.close()
        log.info("LockScreen: скрыт")

    # ── Защита от закрытия ─────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Игнорировать все клавиши (включая Alt+F4, Esc)."""
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Игнорировать закрытие."""
        event.ignore()

    def mousePressEvent(self, event: Any) -> None:
        """Игнорировать клики."""
        event.accept()

"""Определение времени простоя (секунд без ввода мыши/клавиатуры).

Windows: ``GetLastInputInfo`` через ctypes.
Другие ОС (разработка): фоллбэк, считающий от последнего вызова ``touch()``.
"""

from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger(__name__)

# Windows API доступен только на win32
_WIN = sys.platform == "win32"

if _WIN:
    import ctypes
    import ctypes.wintypes

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.wintypes.UINT), ("dwTime", ctypes.wintypes.DWORD)]

    _user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    _kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]


class IdleTracker:
    """Считает секунды без пользовательского ввода."""

    def __init__(self) -> None:
        if not _WIN:
            log.info("IdleTracker: не Windows — использую фоллбэк (ручной touch)")
            self._last_activity: float = time.monotonic()

    def seconds_since_input(self) -> int:
        """Секунд с последнего ввода (мышь/клавиатура)."""
        if _WIN:
            lii = _LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            if _user32.GetLastInputInfo(ctypes.byref(lii)):
                millis = _kernel32.GetTickCount() - lii.dwTime
                return max(0, int(millis // 1000))
            return 0
        # fallback
        return max(0, int(time.monotonic() - self._last_activity))

    def touch(self) -> None:
        """Отметить активность (для не-Windows)."""
        if not _WIN:
            self._last_activity = time.monotonic()

    def get_active_user(self) -> str | None:
        """Имя залогиненного пользователя."""
        try:
            import os

            return os.getlogin()
        except OSError:
            try:
                import getpass

                return getpass.getuser()
            except Exception:
                return None

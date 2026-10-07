"""LL-хук клавиатуры (Windows).

Перехватывает нажатия клавиш на уровне ядра. В блокировке глотает:
Win, Alt+Tab, Win+D, Ctrl+Esc, Alt+F4.

Секретная комбинация Ctrl+Alt+Shift+F12 проходит всегда — по ней
открывается PIN-пад (шаг d).

На Linux (разработка) — заглушка, хук не работает.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import sys
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)

_WIN = sys.platform == "win32"

if _WIN:
    # Windows API constants
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    VK_TAB = 0x09
    VK_ESCAPE = 0x1B
    VK_F12 = 0x7B

    # Модификаторы
    MOD_ALT = 0x0001
    MOD_CTRL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008

    # Структуры
    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", ctypes.wintypes.DWORD),
            ("scanCode", ctypes.wintypes.DWORD),
            ("flags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    # Типы callback
    HOOKPROC = ctypes.CFUNCTYPE(
        ctypes.c_long,  # LRESULT
        ctypes.c_int,  # nCode
        ctypes.wintypes.WPARAM,  # wParam
        ctypes.wintypes.LPARAM,  # lParam
    )

    GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
    CallNextHookEx = ctypes.windll.user32.CallNextHookEx
    SetWindowsHookExW = ctypes.windll.user32.SetWindowsHookExW
    UnhookWindowsHookEx = ctypes.windll.user32.UnhookWindowsHookEx
    GetMessageW = ctypes.windll.user32.GetMessageW
    TranslateMessage = ctypes.windll.user32.TranslateMessage
    DispatchMessageW = ctypes.windll.user32.DispatchMessageW


class KeyboardHook:
    """Low-level хук клавиатуры (Windows).

    Параметры:
        on_secret_combo: callback для секретной комбинации (Ctrl+Alt+Shift+F12).
        is_locked: callable, возвращает True если экран заблокирован.
    """

    def __init__(self, on_secret_combo: Callable[[], None] | None = None, is_locked: Callable[[], bool] | None = None) -> None:
        self._on_secret = on_secret_combo
        self._is_locked = is_locked or (lambda: False)

        self._hook_handle: Any = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Запустить хук в отдельном потоке с message loop."""
        if not _WIN:
            log.warning("KeyboardHook: не Windows — хук не запущен (заглушка)")
            return

        self._thread = threading.Thread(target=self._run, name="keyboard-hook", daemon=True)
        self._thread.start()
        log.info("KeyboardHook: запущен")

    def stop(self) -> None:
        """Остановить хук."""
        self._stop_event.set()
        if self._hook_handle and _WIN:
            try:
                UnhookWindowsHookEx(self._hook_handle)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2)
        log.info("KeyboardHook: остановлен")

    def _run(self) -> None:
        """Поток хука с Windows message loop."""
        if not _WIN:
            return

        # Callback должен быть сохранён, иначе GC его удалит
        self._hook_proc = HOOKPROC(self._hook_callback)
        self._hook_handle = SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, None, 0)

        if not self._hook_handle:
            log.error("KeyboardHook: SetWindowsHookExW failed")
            return

        log.debug("KeyboardHook: хук установлен (handle=%s)", self._hook_handle)

        # Message loop — нужен для LL-хука
        msg = ctypes.wintypes.MSG()
        while not self._stop_event.is_set():
            ret = GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            TranslateMessage(ctypes.byref(msg))
            DispatchMessageW(ctypes.byref(msg))

    def _hook_callback(self, n_code: int, w_param: int, l_param: int) -> int:
        """Callback хука. Возвращает 1 — проглотить клавишу, иначе — передать дальше."""
        if n_code != 0:
            return CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        if w_param not in (WM_KEYDOWN, WM_SYSKEYDOWN):
            return CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        # Извлекаем структуру клавиши
        kb_struct = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk_code = kb_struct.vkCode

        # Проверяем модификаторы
        alt_pressed = GetAsyncKeyState(VK_TAB) & 0x8000 or self._is_key_pressed(0x12)  # VK_MENU = Alt
        ctrl_pressed = self._is_key_pressed(0x11)  # VK_CONTROL
        shift_pressed = self._is_key_pressed(0x10)  # VK_SHIFT
        win_pressed = self._is_key_pressed(0x5B) or self._is_key_pressed(0x5C)  # VK_LWIN / VK_RWIN

        # Секретная комбинация: Ctrl+Alt+Shift+F12 — всегда пропускаем
        if ctrl_pressed and alt_pressed and shift_pressed and vk_code == VK_F12:
            log.info("KeyboardHook: секретная комбинация Ctrl+Alt+Shift+F12")
            if self._on_secret:
                self._on_secret()
            return CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

        # В блокировке глотаем запрещённые клавиши
        if self._is_locked():
            # Alt+Tab
            if alt_pressed and vk_code == VK_TAB:
                log.debug("KeyboardHook: проглочен Alt+Tab")
                return 1

            # Alt+F4
            if alt_pressed and vk_code == VK_F12:  # F4 = 0x74, но здесь проверка на F12 для примера
                pass
            if alt_pressed and vk_code == 0x74:  # VK_F4
                log.debug("KeyboardHook: проглочен Alt+F4")
                return 1

            # Win (любая)
            if vk_code in (0x5B, 0x5C):
                log.debug("KeyboardHook: проглочена Win")
                return 1

            # Win+D, Win+Tab и т.п. — ловим по флагу LLKHF_ALTDOWN или по VK
            # Ctrl+Esc = Start menu
            if ctrl_pressed and vk_code == VK_ESCAPE:
                log.debug("KeyboardHook: проглочен Ctrl+Esc")
                return 1

        return CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

    def _is_key_pressed(self, vk_code: int) -> bool:
        """Проверить, нажата ли клавиша сейчас."""
        if not _WIN:
            return False
        state = GetAsyncKeyState(vk_code)
        return bool(state & 0x8000)

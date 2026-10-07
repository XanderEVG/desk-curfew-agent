"""Точка входа агента desk-curfew.

Шаг (d): конфиг + HTTP-поллинг + события + idle + тосты + BSOD + хук + PIN + fail-open.
Последующий шаг: упаковка PyInstaller (e).
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from agent.config import load_config
from agent.events import EventBuffer
from agent.hooks import KeyboardHook
from agent.http_client import HTTPClient
from agent.idle import IdleTracker
from agent.lock_screen import LockScreen
from agent.pin_dialog import PinDialog
from agent.toast import LockInToast, ToastManager


def _setup_logging(log_file: str, max_mb: int, backups: int) -> None:
    """Ротационный файловый лог + консоль."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    exe_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    fh = logging.handlers.RotatingFileHandler(
        exe_dir / log_file,
        maxBytes=max_mb * 1024 * 1024,
        backupCount=backups,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)


log = logging.getLogger(__name__)


class AgentApp:
    """Главный класс агента. Работает внутри Qt event loop."""

    def __init__(self) -> None:
        self._cfg = load_config()
        _setup_logging(self._cfg.log_file, self._cfg.log_max_mb, self._cfg.log_backups)

        self._command_queue: Queue[dict[str, Any]] = Queue()
        self._events = EventBuffer()
        self._idle = IdleTracker()
        self._http = HTTPClient(
            server_url=self._cfg.server_url,
            agent_token=self._cfg.agent_token,
            pc_name=self._cfg.pc_name,
            heartbeat_interval=self._cfg.heartbeat_interval,
            command_queue=self._command_queue,
            event_buffer=self._events,
            idle_tracker=self._idle,
        )

        self._toasts = ToastManager()
        self._lock_in_toast: LockInToast | None = None
        self._lock_screen: LockScreen | None = None
        self._pin_dialog: PinDialog | None = None

        self._locked = False
        self._lock_reason: str | None = None

        # Хук клавиатуры (Windows)
        self._hook = KeyboardHook(
            on_secret_combo=self._on_secret_combo,
            is_locked=lambda: self._locked,
        )

        # Fail-open таймер (проверка каждые 60 с)
        self._fail_open_timer = QTimer()
        self._fail_open_timer.timeout.connect(self._check_fail_open)

        log.info("Агент инициализирован: pc=%s", self._cfg.pc_name)

    def run(self) -> None:
        """Запуск Qt event loop + HTTP-поллинг."""
        app = QApplication.instance() or QApplication(sys.argv)

        # Таймер обработки команд из HTTP-очереди
        cmd_timer = QTimer()
        cmd_timer.timeout.connect(self._poll_commands)
        cmd_timer.start(500)  # проверка каждые 500 мс

        # Запуск HTTP-потока и хука
        self._http.start()
        self._hook.start()

        # Запуск fail-open таймера (если включён)
        if self._cfg.fail_open_hours > 0:
            self._fail_open_timer.start(60_000)  # проверка каждые 60 с
            log.info("Fail-open: включён (%d часов)", self._cfg.fail_open_hours)

        log.info("Агент запущен (шаг d — HTTP + events + тосты + BSOD + хук + PIN + fail-open)")

        # Graceful shutdown
        app.aboutToQuit.connect(self._shutdown)

        exit_code = app.exec()
        log.info("Qt event loop завершён (exit=%d)", exit_code)

    def _poll_commands(self) -> None:
        """Обработать все накопившиеся команды из очереди."""
        while True:
            try:
                cmd = self._command_queue.get_nowait()
            except Empty:
                break
            self._handle_command(cmd)

    def _handle_command(self, cmd: dict[str, Any]) -> None:
        action = cmd.get("action")
        log.info("Обработка команды: %s", action)

        if action == "lock_now":
            self._cmd_lock_now(cmd)
        elif action == "lock_in":
            self._cmd_lock_in(cmd)
        elif action == "unlock":
            self._cmd_unlock(cmd)
        elif action == "add_time":
            self._cmd_add_time(cmd)
        else:
            log.warning("Неизвестная команда: %s", action)

    def _cmd_lock_now(self, cmd: dict[str, Any]) -> None:
        reason = cmd.get("reason", "manual")
        info = cmd.get("info")

        # Идемпотентность: если уже заблокированы — no-op, но шлём event
        if self._locked:
            log.info("lock_now: уже заблокированы (reason=%s) — no-op + event", self._lock_reason)
            self._events.add("locked", reason)
            return

        # Отменить lock_in таймер, если идёт
        if self._lock_in_toast:
            self._lock_in_toast.cancel()
            self._lock_in_toast = None

        self._locked = True
        self._lock_reason = reason
        self._http.set_locked(True, reason)

        # Показать BSOD-экран
        self._show_lock_screen(info, reason)
        log.info("Заблокировано (reason=%s) — BSOD показан", reason)
        self._events.add("locked", reason)

    def _cmd_lock_in(self, cmd: dict[str, Any]) -> None:
        delay = cmd.get("delay_seconds", 0)
        reason = cmd.get("reason", "manual")

        if delay <= 0:
            # degenerate — блокируем сразу
            log.info("lock_in: delay=0 — блокирую сразу")
            self._cmd_lock_now(cmd)
            return

        # Отменить предыдущий lock_in, если был
        if self._lock_in_toast:
            self._lock_in_toast.cancel()

        self._events.add("warning_shown", reason)
        # Передаём info в callback, чтобы при истечении показать BSOD с данными
        info = cmd.get("info")
        self._lock_in_toast = LockInToast(
            delay,
            on_expire=lambda: self._on_lock_in_expire(reason, info),
        )
        log.info("lock_in: тост с обратным отсчётом %d с (reason=%s)", delay, reason)

    def _on_lock_in_expire(self, reason: str, info: dict[str, Any] | None = None) -> None:
        """По истечении lock_in — блокировать."""
        self._lock_in_toast = None
        self._locked = True
        self._lock_reason = reason
        self._http.set_locked(True, reason)

        # Показать BSOD-экран
        self._show_lock_screen(info, reason)
        log.info("lock_in истёк — заблокировано (reason=%s) — BSOD показан", reason)
        self._events.add("locked", reason)

    def _cmd_unlock(self, cmd: dict[str, Any]) -> None:
        reason = cmd.get("reason", "manual")

        if not self._locked:
            log.info("unlock: не заблокированы — no-op")
            return

        # Отменить lock_in таймер, если идёт
        if self._lock_in_toast:
            self._lock_in_toast.cancel()
            self._lock_in_toast = None

        self._locked = False
        self._lock_reason = None
        self._http.set_locked(False, None)

        # Скрыть BSOD-экран
        self._hide_lock_screen()

        self._toasts.show("🔓 Разблокировано", duration_ms=3000)
        log.info("Разблокировано (reason=%s)", reason)
        self._events.add("unlocked", reason)

    def _cmd_add_time(self, cmd: dict[str, Any]) -> None:
        minutes = cmd.get("minutes", 0)
        self._toasts.show(f"➕ +{minutes} минут", duration_ms=4000)
        log.info("add_time: +%d мин — тост показан", minutes)

    def _show_lock_screen(self, info: dict[str, Any] | None, reason: str) -> None:
        """Показать BSOD-экран блокировки."""
        if self._lock_screen:
            self._lock_screen.hide_lock()
        self._lock_screen = LockScreen(info=info, reason=reason)
        self._lock_screen.show_fullscreen()

    def _hide_lock_screen(self) -> None:
        """Скрыть BSOD-экран."""
        if self._lock_screen:
            self._lock_screen.hide_lock()
            self._lock_screen = None

    def _on_secret_combo(self) -> None:
        """Секретная комбинация Ctrl+Alt+Shift+F12 — показать PIN-пад."""
        log.info("Секретная комбинация — показываю PIN-пад")
        if self._pin_dialog and self._pin_dialog.isVisible():
            self._pin_dialog.hide()

        self._pin_dialog = PinDialog(
            pin_hash=self._cfg.pin_hash,
            on_unlock=self._pin_unlock,
            on_close_agent=self._pin_close_agent,
            on_wrong_pin=self._pin_wrong,
        )
        self._pin_dialog.show()

    def _pin_unlock(self) -> None:
        """PIN верный → Разблокировать."""
        if self._locked:
            self._locked = False
            self._lock_reason = None
            self._http.set_locked(False, None)
            self._hide_lock_screen()
            self._toasts.show("🔓 Разблокировано через PIN", duration_ms=3000)
            self._events.add("unlocked", "pin")
            log.info("PIN: разблокировано")

    def _pin_close_agent(self) -> None:
        """PIN верный → Закрыть агент."""
        log.info("PIN: закрытие агента по решению родителя")
        app = QApplication.instance()
        if app:
            app.quit()

    def _pin_wrong(self) -> None:
        """PIN неверный → event pin_attempt."""
        self._events.add("pin_attempt")
        log.warning("PIN: неверный PIN — event pin_attempt")

    def _check_fail_open(self) -> None:
        """Проверить fail-open: нет связи fail_open_hours подряд + заблокирован → разблокировать."""
        if self._cfg.fail_open_hours <= 0:
            return

        threshold_seconds = self._cfg.fail_open_hours * 3600
        elapsed = self._http.seconds_since_last_success

        if elapsed >= threshold_seconds and self._locked:
            log.critical(
                "Fail-open: нет связи %.1f с (порог %d с) — разблокирую",
                elapsed,
                threshold_seconds,
            )
            self._locked = False
            self._lock_reason = None
            self._http.set_locked(False, None)
            self._hide_lock_screen()
            self._events.add("fail_open")
            self._toasts.show("⚠️ Fail-open: разблокировано (нет связи)", duration_ms=5000)

    def _shutdown(self) -> None:
        self._events.add("agent_stopped")
        self._http.stop()
        self._hook.stop()
        self._toasts.stop()
        self._fail_open_timer.stop()
        if self._lock_screen:
            self._lock_screen.hide_lock()
        if self._pin_dialog:
            self._pin_dialog.hide()
        log.info("Агент остановлен")


def main() -> None:
    app = AgentApp()
    app.run()


if __name__ == "__main__":
    main()

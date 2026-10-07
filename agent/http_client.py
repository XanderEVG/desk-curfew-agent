"""HTTP-клиент: поллинг POST /api/agent/hb, отправка событий, приём команд."""

from __future__ import annotations

import logging
import random
import threading
import time
from queue import Queue
from typing import Any

import requests

log = logging.getLogger(__name__)


class HTTPClient:
    """HTTP-поллинг heartbeat в отдельном потоке.

    Параметры:
        server_url: базовый URL сервера (без trailing slash).
        agent_token: Bearer-токен агента.
        pc_name: имя ПК (используется для логирования).
        heartbeat_interval: интервал между hb в секундах.
        command_queue: очередь для передачи команд в основной поток.
        event_buffer: буфер накопленных событий (drain перед каждым hb).
        idle_tracker: трекер простоя.
    """

    def __init__(
        self,
        server_url: str,
        agent_token: str,
        pc_name: str,
        heartbeat_interval: int,
        command_queue: Queue[dict[str, Any]],
        event_buffer: Any,  # EventBuffer — избегаю циклического импорта
        idle_tracker: Any,  # IdleTracker
    ) -> None:
        self._server_url = server_url
        self._agent_token = agent_token
        self._pc_name = pc_name
        self._interval = heartbeat_interval
        self._queue = command_queue
        self._events = event_buffer
        self._idle = idle_tracker

        self._locked = False
        self._lock_reason: str | None = None
        self._lock = threading.Lock()

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self._agent_token}",
                "Content-Type": "application/json",
            }
        )

        self._backoff = 1.0
        self._server_time: str | None = None

        # Для fail-open: время последнего успешного hb
        import time
        self._last_success_time: float = time.monotonic()

    # ── состояние блокировки (вызывается из основного потока) ─────────

    def set_locked(self, locked: bool, reason: str | None = None) -> None:
        with self._lock:
            self._locked = locked
            self._lock_reason = reason

    @property
    def is_locked(self) -> bool:
        with self._lock:
            return self._locked

    @property
    def lock_reason(self) -> str | None:
        with self._lock:
            return self._lock_reason

    @property
    def server_time(self) -> str | None:
        return self._server_time

    @property
    def seconds_since_last_success(self) -> float:
        """Секунд с последнего успешного hb (для fail-open)."""
        import time
        return time.monotonic() - self._last_success_time

    # ── запуск / остановка ─────────────────────────────────────────────

    def start(self) -> None:
        self._events.add("agent_started")
        self._thread = threading.Thread(target=self._run, name="http-poll", daemon=True)
        self._thread.start()
        log.info("HTTP-поток запущен")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        log.info("HTTP-поток остановлен")

    # ── основной цикл ──────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._send_heartbeat()
                self._backoff = 1.0  # сброс после успеха
            except requests.exceptions.RequestException as exc:
                log.warning("HTTP ошибка: %s", exc)
                self._sleep_backoff()
                continue
            except Exception:
                log.exception("Неожиданная ошибка в HTTP-потоке")
                self._sleep_backoff()
                continue

            # спим интервал, но с возможностью раннего выхода при stop
            if self._stop_event.wait(timeout=self._interval):
                break

    def _send_heartbeat(self) -> None:
        payload = {
            "locked": self.is_locked,
            "lock_reason": self.lock_reason,
            "idle_seconds": self._idle.seconds_since_input(),
            "active_user": self._idle.get_active_user(),
            "events": self._events.drain(),
        }

        url = f"{self._server_url}/api/agent/hb"
        resp = self._session.post(url, json=payload, timeout=5)

        if resp.status_code == 401:
            log.critical("401 Unauthorized — неверный токен? Агент останавливается.")
            self._stop_event.set()
            return

        resp.raise_for_status()

        data = resp.json()
        self._server_time = data.get("server_time")

        # Обновляем время последнего успеха
        import time
        self._last_success_time = time.monotonic()

        commands = data.get("commands", [])
        if commands:
            log.info("Получено %d команд(ы)", len(commands))
        for cmd in commands:
            self._dispatch_command(cmd)

    def _dispatch_command(self, cmd: dict[str, Any]) -> None:
        action = cmd.get("action")
        if action not in ("lock_now", "lock_in", "unlock", "add_time"):
            log.warning("Неизвестная команда: %s", action)
            return
        log.info("Команда: %s", cmd)
        self._queue.put(cmd)

    def _sleep_backoff(self) -> None:
        """Exponential backoff с джиттером, максимум 60 с."""
        jitter = random.uniform(0, 0.3 * self._backoff)
        sleep_time = min(self._backoff + jitter, 60.0)
        log.debug("backoff: sleep %.1fs", sleep_time)
        self._stop_event.wait(timeout=sleep_time)
        self._backoff = min(self._backoff * 2, 60.0)

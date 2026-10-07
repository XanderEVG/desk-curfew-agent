"""Буфер событий — thread-safe накопление событий между heartbeat-ами."""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


class EventBuffer:
    """Накапливает события и отдаёт пачкой для отправки в hb.

    ``drain()`` атомарно возвращает все накопленные события и очищает буфер —
    вызывается из HTTP-потока непосредственно перед формированием payload.
    """

    def __init__(self) -> None:
        self._events: list[dict] = []
        self._lock = threading.Lock()

    def add(self, event: str, reason: str | None = None) -> None:
        entry: dict = {"event": event}
        if reason is not None:
            entry["reason"] = reason
        with self._lock:
            self._events.append(entry)
        log.debug("event queued: %s", entry)

    def drain(self) -> list[dict]:
        """Забрать все события и очистить буфер."""
        with self._lock:
            out = list(self._events)
            self._events.clear()
            return out

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

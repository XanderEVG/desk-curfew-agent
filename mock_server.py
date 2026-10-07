"""Минимальный mock-сервер для локальной разработки.

Запуск:  uvicorn mock_server:app --host 0.0.0.0 --port 8000

Можно подавать команды агенту через интерактивный ввод в консоли сервера
или через отдельный HTTP-запрос (см. ``POST /push``).
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from fastapi import FastAPI, Header
from pydantic import BaseModel

app = FastAPI(title="desk-curfew mock server")

# Очередь команд — агент заберёт их в следующем hb
_pending_commands: list[dict] = []
_lock = threading.Lock()


class Heartbeat(BaseModel):
    locked: bool = False
    lock_reason: str | None = None
    idle_seconds: int = 0
    active_user: str | None = None
    events: list[dict] = []


class PushCommand(BaseModel):
    """Тело для POST /push — добавить команду в очередь."""

    action: str
    delay_seconds: int | None = None
    reason: str | None = None
    minutes: int | None = None
    info: dict | None = None


@app.post("/api/agent/hb")
async def heartbeat(payload: Heartbeat, authorization: str | None = Header(None)):
    if payload.events:
        print(f"  events: {payload.events}")

    with _lock:
        commands = list(_pending_commands)
        _pending_commands.clear()

    return {
        "commands": commands,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/push")
async def push_command(cmd: PushCommand):
    """Добавить команду — агент заберёт в следующем hb."""
    data: dict = {"action": cmd.action}
    if cmd.delay_seconds is not None:
        data["delay_seconds"] = cmd.delay_seconds
    if cmd.reason is not None:
        data["reason"] = cmd.reason
    if cmd.minutes is not None:
        data["minutes"] = cmd.minutes
    if cmd.info is not None:
        data["info"] = cmd.info

    with _lock:
        _pending_commands.append(data)

    print(f"  queued: {data}")
    return {"ok": True, "queued": data}

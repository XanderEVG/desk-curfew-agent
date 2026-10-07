"""Загрузка конфигурации из config.ini."""

from __future__ import annotations

import configparser
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentConfig:
    pc_name: str
    server_url: str
    agent_token: str
    heartbeat_interval: int

    pin_hash: str
    fail_open_hours: int

    log_file: str
    log_max_mb: int
    log_backups: int


def _exe_dir() -> Path:
    """Директория исполняемого файла (или скрипта при разработке)."""
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def load_config(path: str | Path | None = None) -> AgentConfig:
    """Загрузить конфигурацию из INI-файла.

    Если *path* не задан, ищет ``config.ini`` рядом с exe/скриптом.
    """
    if path is None:
        path = _exe_dir() / "config.ini"
    path = Path(path)

    if not path.is_file():
        raise FileNotFoundError(f"Конфиг не найден: {path}")

    cp = configparser.ConfigParser()
    cp.read(path, encoding="utf-8")

    def get(section: str, key: str, fallback: str = "") -> str:
        return cp.get(section, key, fallback=fallback).strip()

    def getint(section: str, key: str, fallback: int = 0) -> int:
        try:
            return cp.getint(section, key, fallback=fallback)
        except ValueError:
            log.warning("Некорректное целое %s.%s — использую %d", section, key, fallback)
            return fallback

    cfg = AgentConfig(
        pc_name=get("agent", "pc_name"),
        server_url=get("agent", "server_url", "http://127.0.0.1:8000").rstrip("/"),
        agent_token=get("agent", "agent_token"),
        heartbeat_interval=getint("agent", "heartbeat_interval", 10),
        pin_hash=get("security", "pin_hash"),
        fail_open_hours=getint("security", "fail_open_hours", 12),
        log_file=get("logging", "log_file", "agent.log"),
        log_max_mb=getint("logging", "log_max_mb", 5),
        log_backups=getint("logging", "log_backups", 3),
    )

    if not cfg.pc_name:
        raise ValueError("agent.pc_name обязателен")
    if not cfg.agent_token:
        raise ValueError("agent.agent_token обязателен")

    log.info("Конфиг загружен: pc=%s url=%s interval=%ds", cfg.pc_name, cfg.server_url, cfg.heartbeat_interval)
    return cfg

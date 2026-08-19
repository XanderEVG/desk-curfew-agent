import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import yaml
from PyQt6.QtWidgets import QApplication

from lock_window import LockWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("agent.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("kids_agent")


class KidsAgent:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        self.pc_name = self.cfg["pc_name"]
        self.mqtt_cfg = self.cfg["mqtt"]
        self.topic_prefix = self.mqtt_cfg["topic_prefix"]

        self.locked = False
        self.lock_reason = None
        self.lock_window = None
        self.qt_app = None

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"agent-{self.pc_name}",
        )

        if self.mqtt_cfg.get("use_ssl"):
            self.client.tls_set()

        self.client.username_pw_set(
            self.mqtt_cfg["username"],
            self.mqtt_cfg["password"]
        )

        # Last Will: если агент упадёт, сервер узнает
        self.client.will_set(
            f"{self.topic_prefix}/{self.pc_name}/status",
            json.dumps({"online": False, "ts": self._now_iso()}),
            qos=1, retain=True
        )

        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

    def _now_iso(self):
        return datetime.now(timezone.utc).isoformat()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            log.info("Подключён к MQTT!")
            client.subscribe(f"{self.topic_prefix}/{self.pc_name}/cmd", qos=1)
            self._publish_status()
            self._publish_event("agent_started")
        else:
            log.error(f"Ошибка подключения к MQTT: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning(f"Отключён от MQTT: {reason_code}")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            action = payload.get("action")
            log.info(f"Получена команда: {action} -> {payload}")

            if action == "lock_now":
                self._do_lock(payload.get("reason", "manual"))
            elif action == "lock_in":
                self._schedule_lock(payload)
            elif action == "unlock":
                self._do_unlock(payload.get("reason", "manual"))
            elif action == "shutdown_in":
                self._schedule_shutdown(payload)
            elif action == "add_time":
                log.info("Добавлено время, сбрасываем таймеры блокировки")

        except Exception as e:
            log.error(f"Ошибка обработки сообщения: {e}")

    def _do_lock(self, reason):
        if self.locked: return
        self.locked = True
        self.lock_reason = reason
        log.info(f"Блокировка: {reason}")
        self._publish_event("locked", reason=reason)
        self._publish_status()

        # Показываем окно в главном потоке Qt
        if self.qt_app:
            self.qt_app.show_lock_window(reason)

    def _do_unlock(self, reason):
        if not self.locked: return
        self.locked = False
        self.lock_reason = None
        log.info(f"Разблокировка: {reason}")
        self._publish_event("unlocked", reason=reason)
        self._publish_status()

        if self.qt_app:
            self.qt_app.hide_lock_window()

    def _schedule_lock(self, payload):
        delay = payload.get("delay_seconds", 300)
        reason = payload.get("reason", "schedule")

        def _run():
            log.info(f"Запланирована блокировка через {delay} сек")
            time.sleep(delay)
            if not self.locked:
                self._do_lock(reason)

        threading.Thread(target=_run, daemon=True).start()

    def _schedule_shutdown(self, payload):
        delay = payload.get("delay_seconds", 60)

        def _run():
            time.sleep(delay)
            log.info("Выключаю компьютер...")
            subprocess.run(["shutdown", "/s", "/f", "/t", "0"])

        threading.Thread(target=_run, daemon=True).start()

    def _publish_status(self):
        topic = f"{self.topic_prefix}/{self.pc_name}/status"
        payload = {
            "online": True,
            "locked": self.locked,
            "lock_reason": self.lock_reason,
            "user": os.environ.get("USERNAME", "unknown"),
            "ts": self._now_iso()
        }
        self.client.publish(topic, json.dumps(payload), qos=1, retain=True)

    def _publish_event(self, event, **kwargs):
        topic = f"{self.topic_prefix}/{self.pc_name}/event"
        payload = {"event": event, "ts": self._now_iso(), **kwargs}
        self.client.publish(topic, json.dumps(payload), qos=1)

    def _publish_heartbeat(self):
        topic = f"{self.topic_prefix}/{self.pc_name}/hb"
        payload = {
            "ts": self._now_iso(),
            "active_user": os.environ.get("USERNAME", "unknown"),
            "locked": self.locked
        }
        self.client.publish(topic, json.dumps(payload), qos=0)

    def run_mqtt_loop(self):
        self.client.connect(
            self.mqtt_cfg["host"],
            self.mqtt_cfg.get("port", 9992),
            keepalive=60
        )
        self.client.loop_start()

        interval = self.cfg.get("heartbeat_interval", 30)
        try:
            while True:
                self._publish_heartbeat()
                time.sleep(interval)
        except KeyboardInterrupt:
            self.client.loop_stop()
            self.client.disconnect()


class QtAppManager:
    """Менеджер для безопасного вызова GUI из потока MQTT."""

    def __init__(self):
        self.app = QApplication(sys.argv)
        self.window = None

    def show_lock_window(self, reason):
        if not self.window:
            self.window = LockWindow(reason)
        self.window.show_fullscreen()

    def hide_lock_window(self):
        if self.window:
            self.window.close()
            self.window = None

    def start_qt_loop(self):
        # Запускает Qt event loop. Он будет крутиться в главном потоке.
        sys.exit(self.app.exec())


if __name__ == "__main__":
    agent = KidsAgent()
    qt_manager = QtAppManager()
    agent.qt_app = qt_manager

    # Запускаем MQTT и heartbeat в отдельном потоке
    mqtt_thread = threading.Thread(target=agent.run_mqtt_loop, daemon=True)
    mqtt_thread.start()

    # Главный поток отдаём под Qt (иначе окно не будет реагировать)
    qt_manager.start_qt_loop()
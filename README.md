# desk-curfew-agent

Агент desk-curfew для Windows. Устанавливается на детские компьютеры
(Windows 10/11).

Агент — только исполнитель. Вся логика расписаний, лимитов и решений
находится на сервере (desk-curfew-server). Агент получает команды через
**HTTP** (поллинг heartbeat), показывает полноэкранный экран блокировки,
отправляет heartbeat и события.

## Архитектура

- Обмен с сервером — **HTTP** (поллинг `POST /api/agent/hb` каждые 10 с).
- Агент не знает расписания и лимитов: сервер присылает готовые решения
  и данные для экрана блокировки (блок `info` в lock-командах).
- Полный протокол и семантика — в `docs/agent_protocol.md` и
  `docs/agent_http_protocol.md`.

## Возможности

- HTTP-поллинг heartbeat каждые 10 с с `idle_seconds` (через `GetLastInputInfo`) —
  сервер различает «ребёнок за ПК», «отошёл» и «агент умер».
- Автореконнект при ошибках HTTP (exponential backoff, максимум 60 с).
- Команды: `lock_now`, `lock_in`, `unlock`, `add_time` (с блоком `info`).
- Полноэкранный BSOD-экран блокировки (PySide6): без рамки, topmost,
  поверх таскбара, скрыт из Alt+Tab (`WS_EX_TOOLWINDOW`), игнор Alt+F4/WM_CLOSE.
- Low-level хук клавиатуры: в блокировке глотает Win, Alt+Tab, Win+D,
  Ctrl+Esc, Alt+F4; секретная комбинация проходит всегда.
- Тосты поверх всех окон без кражи фокуса: отсчёт блокировки, «+N минут»,
  «Разблокировано».
- Аварийный доступ: Ctrl+Alt+Shift+F12 → PIN-пад (хеш PIN в конфиге; при
  первом запуске агент просит создать PIN). Неверный PIN → событие `pin_attempt`.
- Fail-open: авто-разблокировка при потере связи с сервером дольше
  `fail_open_hours` (дефолт 12, `0` = выключено) + событие `fail_open`.
- Автозапуск при входе в систему с наивысшими правами (Task Scheduler).
- Логирование в файл рядом с exe.

## Стек

- Python 3.12+
- PySide6 (экран блокировки, тосты, PIN-пад)
- requests (HTTP-клиент)
- ctypes (LL-хук клавиатуры, `GetLastInputInfo`)
- PyInstaller (сборка в .exe, `--uac-admin`)

## Конфиг

`config.ini` рядом с exe:

```ini
[agent]
pc_name = evgeny_pc
server_url = http://192.168.1.100:8000
agent_token = <токен из веб-интерфейса сервера>
heartbeat_interval = 10

[security]
pin_hash =
fail_open_hours = 12

[logging]
log_file = agent.log
log_max_mb = 5
log_backups = 3
```

См. `config.ini.example`.

## Команды

| Команда | Параметры | Описание |
| --- | --- | --- |
| `lock_now` | `reason`, `info` | Немедленная блокировка |
| `lock_in` | `delay_seconds`, `reason`, `info` | Тост с отсчётом, затем блокировка |
| `unlock` | `reason` | Разблокировка |
| `add_time` | `minutes` | Информационная: тост «+N минут», агент не разблокирует сам |

Блок `info` (сервер считает — агент рисует): `display_name`, `reason`,
`reason_ru`, `locked_at`, `unlocks_at`, `next_window`. Стоп-коды на экране:
`CURFEW_DAILY_LIMIT` / `CURFEW_SCHEDULE` / `CURFEW_MANUAL`.

## События агента

`agent_started`, `agent_stopped`, `locked`, `unlocked`, `warning_shown`,
`pin_attempt`, `fail_open`.

## Сборка

```bat
pip install -r requirements.txt
build.bat
```

Результат: `dist\DeskCurfewAgent.exe`.

## Установка на детский ПК

1. Скопировать `DeskCurfewAgent.exe` и `config.ini` в `C:\curfew\`.
2. Запустить `install_task.bat` от имени администратора — создаст задачу
   Планировщика: триггер «при входе в систему», «выполнять с наивысшими
   правами» (elevated без UAC-промта).
3. Проверить, что UAC включён (`EnableLUA = 1`) — на этом держится защита
   от неповышенного Диспетчера задач.
4. Перезагрузить компьютер, убедиться, что агент запустился (лог, hb на сервере).

## Аварийный доступ

Ctrl+Alt+Shift+F12 → PIN-пад → меню «Разблокировать / Закрыть агент / Отмена».
PIN хранится в конфиге только как хеш.
Fail-open страхует сценарий «сервер умер надолго».

## Ограничения (текущий этап)

- Агент работает в пользовательской сессии, не как служба.
- Ctrl+Alt+Del не блокируется (ограничение Windows).
- Ребёнок может повысить Диспетчер задач через UAC-промт и завершить процесс.
- Задачу Планировщика можно отключить, зная где искать.

Эти ограничения осознанные. Роадмап ужесточения: watchdog-пара, служба,
групповые политики, BlockInput.

## Лицензия

MIT

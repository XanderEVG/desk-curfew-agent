@echo off
REM Установка агента desk-curfew в Task Scheduler (автозапуск при входе)

echo === desk-curfew agent install ===
echo.

REM Проверка прав администратора
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Запустите от имени администратора
    exit /b 1
)

REM Проверка UAC (EnableLUA)
for /f "tokens=3" %%a in ('reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v EnableLUA 2^>nul') do set ENABLELUA=%%a
if "%ENABLELUA%" neq "1" (
    echo WARNING: UAC не включён (EnableLUA=%ENABLELUA%)
    echo Агент работает, но защита от неповышенного Диспетчера задач не действует.
    echo Рекомендуется включить UAC.
    echo.
    pause
)

REM Путь к exe
set AGENT_PATH=%~dp0DeskCurfewAgent.exe
if not exist "%AGENT_PATH%" (
    echo ERROR: DeskCurfewAgent.exe не найден в %~dp0
    echo Скопируйте exe рядом с этим скриптом.
    exit /b 1
)

echo Путь к агенту: %AGENT_PATH%
echo.

REM Удаление старой задачи (если есть)
schtasks /delete /tn "desk-curfew" /f >nul 2>&1

REM Создание задачи
schtasks /create ^
    /sc onlogon ^
    /rl HIGHEST ^
    /tn "desk-curfew" ^
    /tr "\"%AGENT_PATH%\"" ^
    /f

if %ERRORLEVEL% neq 0 (
    echo ERROR: Не удалось создать задачу
    exit /b 1
)

echo.
echo === Готово ===
echo Задача "desk-curfew" создана:
echo   - Триггер: при входе в систему
echo   - Права: наивысшие (elevated без UAC-промта)
echo   - Команда: %AGENT_PATH%
echo.
echo Перезагрузите компьютер для проверки автозапуска.
echo.

REM Предложение запустить сейчас
set /p RUN_NOW="Запустить агент сейчас? (y/n): "
if /i "%RUN_NOW%"=="y" (
    echo Запуск...
    start "" "%AGENT_PATH%"
    echo Агент запущен. Проверьте лог: %~dp0agent.log
)

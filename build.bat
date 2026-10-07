@echo off
REM Сборка агента desk-curfew в .exe через PyInstaller

echo === desk-curfew agent build ===
echo.

REM Проверка venv
if not exist ".venv\Scripts\python.exe" (
    echo ERROR: venv не найден. Создайте: python -m venv .venv
    exit /b 1
)

REM Активация venv
call .venv\Scripts\activate.bat

REM Установка зависимостей (если нужно)
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller

echo.
echo === Сборка ===
pyinstaller --onefile ^
    --uac-admin ^
    --name DeskCurfewAgent ^
    --add-data "config.ini.example;." ^
    --hidden-import PySide6.QtCore ^
    --hidden-import PySide6.QtGui ^
    --hidden-import PySide6.QtWidgets ^
    agent\main.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo ERROR: PyInstaller failed
    exit /b 1
)

echo.
echo === Готово ===
echo Результат: dist\DeskCurfewAgent.exe
echo.
echo Скопируйте dist\DeskCurfewAgent.exe и config.ini на детский ПК.
echo Запустите install_task.bat от имени администратора.

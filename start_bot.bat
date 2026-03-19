@echo off
chcp 65001 > nul
title Основной бот Казино
echo Запуск основного бота...
cd /d "%~dp0"

:: Проверка и активация виртуального окружения
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo Виртуальное окружение не найдено. Создаю и устанавливаю зависимости...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
)

python bot.py
pause
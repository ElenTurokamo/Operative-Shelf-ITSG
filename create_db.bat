@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

echo Запуск инициализации базы данных...
python create_db.py
pause
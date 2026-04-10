@echo off
title CryptoPi Local

if not exist .venv\ (
    echo ❌ Error: Virtual environment not found. Please run setup.bat first.
    pause
    exit /b 1
)

if not exist coinbase_keys.json (
    echo ❌ Error: coinbase_keys.json is missing. Please run setup.bat first.
    pause
    exit /b 1
)

echo 🚀 Booting CryptoPi Local...
call .venv\Scripts\activate.bat
python app.py
pause
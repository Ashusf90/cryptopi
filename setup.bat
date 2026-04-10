@echo off
setlocal enabledelayedexpansion
title CryptoPi Local Setup

echo ==========================================
echo 🚀 Initializing CryptoPi Local Setup...
echo ==========================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Error: Python is not installed or not in your PATH.
    pause
    exit /b 1
)

if not exist .venv\ (
    echo -^> Creating Python virtual environment ^(.venv^)...
    python -m venv .venv
)

echo -^> Installing Python dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt >nul 2>&1
echo ✅ Dependencies installed.

if not exist .env (
    echo.
    echo --- 🔐 Dashboard Security Setup ---
    set /p admin_user="Enter a new Admin Username [admin]: "
    if "!admin_user!"=="" set admin_user=admin

    set /p admin_pass="Enter a new Admin Password [password123]: "
    if "!admin_pass!"=="" set admin_pass=password123

    echo FLASK_SECRET_KEY="local_secure_key_!random!!random!!random!" > .env
    echo ADMIN_USERNAME="!admin_user!" >> .env
    echo ADMIN_PASSWORD="!admin_pass!" >> .env
    echo ✅ .env file generated successfully.
) else (
    echo -^> .env already exists. Skipping generation.
)

if not exist config.json (
    copy config.example.json config.json >nul
    echo ✅ Default config.json generated.
)

echo.
echo =================================================================
echo ⚠️  CRITICAL SECURITY STEP: COINBASE API KEYS
echo =================================================================
echo For your safety during testing, it is STRONGLY recommend creating a
echo NEW, dedicated Coinbase API Key with strictly READ-ONLY permissions.
echo Do NOT use a key with Transfer, Trade, or Withdraw permissions
echo until you are ready to risk real capital in Live Mode.
echo.
echo 1. Download your 'coinbase_keys.json' file from Coinbase.
echo 2. Move or paste that file directly into this folder.
echo    (Make sure it is named exactly 'coinbase_keys.json')
echo.
set /p key_choice="Press [Enter] when you have added the file, or type 'skip' to use a placeholder: "

if not exist coinbase_keys.json (
    echo -^> File not detected or skipped. Generating placeholder coinbase_keys.json.
    echo    You will need to manually edit this file before running the bot.
    copy coinbase_keys.example.json coinbase_keys.json >nul
) else (
    echo ✅ coinbase_keys.json detected successfully!
)

echo.
echo ==========================================
echo 🎉 SETUP COMPLETE!
echo ==========================================
echo ⚠️ FINAL STEP: If you skipped the file upload step, you MUST open
echo    'coinbase_keys.json' in a text editor and paste your API Name
echo    and Private Key from Coinbase before running the bot.
echo.
echo Once your keys are saved, you can start the bot at any time by running:
echo.
echo     +----------------+
echo     ^|   start.bat    ^|
echo     +----------------+
echo.
echo =================================================================
pause
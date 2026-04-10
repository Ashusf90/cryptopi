#!/bin/bash

echo "=========================================="
echo "🚀 Initializing CryptoPi Local Setup..."
echo "=========================================="

# 1. Check for Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed. Please install Python 3.9+."
    exit 1
fi

# 2. Virtual Environment
if [ ! -d ".venv" ]; then
    echo "-> Creating Python virtual environment (.venv)..."
    python3 -m venv .venv
fi

# 3. Dependencies
source .venv/bin/activate
echo "-> Installing Python dependencies..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo "✅ Dependencies installed."

# 4. Interactive .env Generator
if [ ! -f ".env" ]; then
    echo ""
    echo "--- 🔐 Dashboard Security Setup ---"
    read -p "Enter a new Admin Username [admin]: " admin_user
    admin_user=${admin_user:-admin}

    read -p "Enter a new Admin Password [password123]: " admin_pass
    admin_pass=${admin_pass:-password123}

    # Generate a random 24-byte hex string for session security
    flask_secret=$(openssl rand -hex 24 2>/dev/null || echo "fallback_secret_key_$(date +%s)")

    cat <<EOF > .env
# CryptoPi Local Environment
FLASK_SECRET_KEY="$flask_secret"
ADMIN_USERNAME="$admin_user"
ADMIN_PASSWORD="$admin_pass"
EOF
    echo "✅ .env file generated successfully."
else
    echo "-> .env already exists. Skipping generation."
fi

# 5. Configuration Templates
if [ ! -f "config.json" ]; then
    cp config.example.json config.json
    echo "✅ Default config.json generated."
fi

echo ""
echo "================================================================="
echo "⚠️  CRITICAL SECURITY STEP: COINBASE API KEYS"
echo "================================================================="
echo "For your safety during testing, it is STRONGLY recommend creating a"
echo "NEW, dedicated Coinbase API Key with strictly READ-ONLY permissions."
echo "Do NOT use a key with Transfer, Trade, or Withdraw permissions"
echo "until you are ready to risk real capital in Live Mode."
echo ""
echo "1. Download your 'coinbase_keys.json' file from Coinbase."
echo "2. Move or paste that file directly into this folder."
echo "   (Make sure it is named exactly 'coinbase_keys.json')"
echo ""
read -p "Press [Enter] when you have added the file, or type 'skip' to use a placeholder: " key_choice

if [ ! -f "coinbase_keys.json" ]; then
    echo "-> File not detected or skipped. Generating placeholder coinbase_keys.json."
    echo "   You will need to manually edit this file before running the bot."
    cp coinbase_keys.example.json coinbase_keys.json
else
    echo "✅ coinbase_keys.json detected successfully!"
fi

echo ""
# 6. Fix execution permissions for the start script
if [ -f "start.sh" ]; then
    chmod +x start.sh
fi

echo "=========================================="
echo "✅ Setup Complete!"
echo "=========================================="
echo "⚠️ FINAL STEP: If you skipped the file upload step, you MUST open"
echo "   'coinbase_keys.json' in a text editor and paste your API Name"
echo "   and Private Key from Coinbase before running the bot."
echo ""
echo "Once your keys are saved, you can start the bot at any time by running:"
echo ""
echo "    +----------------+"
echo "    |   ./start.sh   |"
echo "    +----------------+"
echo ""
echo "================================================================="
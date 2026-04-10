#!/bin/bash

# Check if setup has been run
if [ ! -d ".venv" ]; then
    echo "❌ Error: Virtual environment not found. Please run ./setup.sh first."
    exit 1
fi

if [ ! -f "coinbase_keys.json" ]; then
    echo "❌ Error: coinbase_keys.json is missing. Please run ./setup.sh first."
    exit 1
fi

echo "🚀 Booting CryptoPi Local..."
source .venv/bin/activate
python app.py
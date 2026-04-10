import ccxt
import json
import time
import os

# --- CONFIG ---
CONFIG_FILE = 'config.json'

def load_config():
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def check_zombies():
    print("🧟 Starting Zombie Symbol Scan...")
    config = load_config()
    
    # Get Blacklist
    blacklist = config.get('dynamic_symbols_config', {}).get('blacklist', [])
    if not blacklist:
        print("✅ Blacklist is empty! No zombies to check.")
        return

    print(f"📋 Found {len(blacklist)} symbols in blacklist: {blacklist}")
    
    # Setup Exchange
    exchange_id = config.get('exchange', 'coinbase')
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({
        'apiKey': os.getenv('COINBASE_API_KEY'),
        'secret': os.getenv('COINBASE_API_SECRET'),
        'timeout': 30000,
        'enableRateLimit': True
    })

    resurrected = []
    
    for symbol in blacklist:
        print(f"   👉 Poking {symbol}...", end=" ")
        try:
            # Test 1: Fetch Ticker
            ticker = exchange.fetch_ticker(symbol)
            if ticker['bid'] is None or ticker['ask'] is None:
                raise Exception("No Bid/Ask data")
            
            # Test 2: Fetch Candles (The real test for volatility calc)
            candles = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=5)
            if not candles or len(candles) < 1:
                raise Exception("No Candle data")
                
            print("✅ ALIVE! (Data is valid)")
            resurrected.append(symbol)
            
        except Exception as e:
            print(f"💀 DEAD. ({str(e)})")
        
        time.sleep(0.5) # Be nice to API

    print("-" * 40)
    if resurrected:
        print(f"✨ {len(resurrected)} Symbols have resurrected!")
        print(f"   Suggestion: Remove these from 'blacklist' in config.json:")
        print(f"   {json.dumps(resurrected, indent=4)}")
    else:
        print("⚰️  All zombies are still dead. Keep them blacklisted.")

if __name__ == "__main__":
    try:
        check_zombies()
    except KeyboardInterrupt:
        print("\nScan cancelled.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
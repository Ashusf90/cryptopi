import ccxt
import json
import pandas as pd
import pandas_ta as ta
import glob
import os
import time
import re
from colorama import init, Fore, Style

# --- CONFIG ---
TARGET_TIMEFRAME = '1h'
LOOKBACK_CANDLES = 24  # Check last 24 hours of data
TOP_N_GAINERS = 5

def load_json(filepath):
    """
    Robust JSON loader that handles C-style comments (//).
    """
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            content = re.sub(r'//.*', '', content)
            return json.loads(content)
    except Exception as e:
        # Return empty dict on failure so the bot doesn't crash
        return {}

def get_top_gainers(exchange, limit=5):
    tickers = exchange.fetch_tickers()
    usd_pairs = {k: v for k, v in tickers.items() if '/USD' in k and 'USDC' not in k and 'USDT' not in k}
    sorted_tickers = sorted(usd_pairs.items(), key=lambda x: x[1]['percentage'] if x[1]['percentage'] else -999, reverse=True)
    return sorted_tickers[:limit]

def simulate_logic(df, config, symbol):
    if df.empty: return False, "No Data"
    
    # 1. Indicators
    rsi_len = config.get('rsi_config', {}).get('period', 14)
    df.ta.rsi(length=rsi_len, append=True)
    current_rsi = df[f'RSI_{rsi_len}'].iloc[-1]
    
    adx_len = config.get('adx_period', 14)
    df.ta.adx(length=adx_len, append=True)
    current_adx = df[f'ADX_{adx_len}'].iloc[-1]
    
    vol_period = config.get('volume_confirmation', {}).get('period', 14)
    median_vol = df['volume'].rolling(window=vol_period).median().iloc[-1]
    current_vol = df['volume'].iloc[-1]
    vol_tgt = median_vol * config.get('volume_confirmation', {}).get('multiplier', 1.5)
    
    # 2. Rejection Logic
    pct_change = (df['close'].iloc[-1] - df['open'].iloc[0]) / df['open'].iloc[0] * 100
    max_pump = config.get('max_24h_change_threshold', 30.0)
    if pct_change > max_pump:
        return False, f"PUMP LIMIT ({pct_change:.1f}% > {max_pump}%)"

    if config.get('volume_confirmation', {}).get('enabled', True):
        if current_vol < vol_tgt:
            return False, f"LOW VOL ({current_vol:.0f} < {vol_tgt:.0f})"

    rsi_max = config.get('rsi_config', {}).get('overbought', 70)
    if current_rsi > rsi_max:
        return False, f"RSI OVERBOUGHT ({current_rsi:.1f} > {rsi_max})"

    trend_thresh = config.get('adx_trending_threshold', 25)
    is_trending = current_adx > trend_thresh
    
    if is_trending:
        return True, f"BUY SIGNAL (Trending ADX {current_adx:.1f})"
    else:
        rsi_min = config.get('rsi_config', {}).get('oversold', 30)
        if current_rsi < rsi_min:
            return True, f"DIP BUY (RSI {current_rsi:.1f} < {rsi_min})"
        else:
            return False, f"NO SIGNAL (ADX {current_adx:.1f}, RSI {current_rsi:.1f})"

def fetch_audit_report(is_web=False):
    """
    Main function called by app.py (is_web=True) or terminal (is_web=False).
    Returns a string containing the full report.
    """
    if not is_web: init(autoreset=True)
    
    output = []
    
    def log(text):
        output.append(str(text))

    # Helper for colors
    def color_text(text, color_name):
        if is_web:
            # HTML Colors for Web
            c = "#ccc"
            if color_name == "CYAN": c = "#00bcd4" # Bright Blue
            if color_name == "GREEN": c = "#2ecc71"
            if color_name == "RED": c = "#e74c3c"
            return f'<span style="color: {c}; font-weight: bold;">{text}</span>'
        else:
            # ANSI Colors for Terminal
            c = ""
            if color_name == "CYAN": c = Fore.CYAN + Style.BRIGHT
            if color_name == "GREEN": c = Fore.GREEN
            if color_name == "RED": c = Fore.RED
            return f"{c}{text}{Style.RESET_ALL}" if not is_web else text

    try:
        log("🔍 Scanning Market for Top Gainers...")
        
        exchange = ccxt.coinbase({
            'timeout': 30000, 
            'enableRateLimit': True,
            'apiKey': os.getenv('COINBASE_API_KEY'),
            'secret': os.getenv('COINBASE_API_SECRET'),
        })
        
        top_gainers = get_top_gainers(exchange, TOP_N_GAINERS)
        
        # Glob patterns logic to find config files
        # We need absolute path if running from app.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        search_path = os.path.join(current_dir, "config*.json")
        config_files = glob.glob(search_path)
        
        # Sort: CURRENT first, then alphabetical
        config_files.sort(key=lambda f: (os.path.basename(f) != 'config.json', f))
        
        log(f"📂 Found Profiles: {[os.path.basename(f) for f in config_files]}")
        log("\n" + "="*60)
        log("📢 FOMO DETECTOR REPORT")
        log("="*60)
        
        for symbol, ticker in top_gainers:
            change_24h = ticker['percentage']
            price = ticker['last']
            
            log(f"\n🚀 {symbol} (+{change_24h:.2f}%) @ ${price}")
            
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TARGET_TIMEFRAME, limit=100)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            except:
                log("   ⚠️ Failed to fetch history.")
                continue

            for cfg_file in config_files:
                base_name = os.path.basename(cfg_file)
                cfg_name = base_name.replace('.json', '').replace('config_', '').upper()
                if cfg_name == "CONFIG": cfg_name = "CURRENT"
                
                config = load_json(cfg_file)
                if not config: continue
                
                should_buy, reason = simulate_logic(df, config, symbol)
                
                icon = "✅" if should_buy else "❌"
                line = f"   [{cfg_name:<10}] {icon} {reason}"
                
                if cfg_name == "CURRENT":
                    log(color_text(line, "CYAN"))
                else:
                    log(line)
                    
        log("\n" + "="*60)
        return "\n".join(output)

    except Exception as e:
        return f"Error running audit: {str(e)}"

if __name__ == "__main__":
    # When run directly from terminal
    print(fetch_audit_report(is_web=False))
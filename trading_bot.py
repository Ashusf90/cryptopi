import ccxt
import json
import time
import math
from datetime import datetime
import os
import csv
from colorama import init, Style 
from dotenv import load_dotenv

# Initialize environment variables
load_dotenv()
import pandas as pd
import pandas_ta as ta
import sys
import hashlib
import io, queue, threading
import sqlite3
import re
from strategies.standard import StandardStrategy
from strategies.accumulator import AccumulatorStrategy
# Initialize the strategy globally for the functional loop to access
# --- STRATEGY ENGINE LOADER ---
STRATEGY_ENGINE = None

def load_strategy_engine(config):
    global STRATEGY_ENGINE
    profile = config.get('strategy_profile', 'standard').lower()
    
    if profile == 'accumulator':
        STRATEGY_ENGINE = AccumulatorStrategy()
        log_terminal("🌌 STRATEGY LOADED: Event Horizon (Accumulator)")
    else:
        STRATEGY_ENGINE = StandardStrategy()
        log_terminal("📈 STRATEGY LOADED: Standard Trend Bot")


# --- ARCHITECTURAL FIXES ---

RUNTIME_BLACKLIST = set()
GLOBAL_EVENT_QUEUE = None 
GLOBAL_LOG_QUEUE = None   
original_stdout = sys.stdout 

def log_event(message, event_type="info"):
    """Sends clean, structured message to the event queue."""
    if GLOBAL_EVENT_QUEUE:
        GLOBAL_EVENT_QUEUE.put({
            "message": message, 
            "type": event_type
        })

def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)
        
def log_terminal(message, color_code=""):
    if color_code:
        colored_msg = f"{color_code}{message}{Style.RESET_ALL}"
    else:
        colored_msg = message

    if original_stdout:
        try:
            ts = datetime.now().strftime('%H:%M:%S')
            original_stdout.write(f"[{ts}] {colored_msg}\n")
            original_stdout.flush()
        except Exception: pass

    log_analysis(colored_msg if color_code else message)

def log_analysis(message):
    if GLOBAL_LOG_QUEUE:
        GLOBAL_LOG_QUEUE.put(message)

from colorama import init, Style
init(strip=False)

stop_requested = False

# --- UTILITY AND DATA FUNCTIONS ---

def load_portfolio(config):
    try:
        with open('portfolio.json', 'r') as f: return json.load(f)
    except FileNotFoundError:
        log_analysis("No portfolio.json found, creating a new one...")
        starting_capital = config.get('starting_capital', 1000.0)
        new_portfolio = {"cash": starting_capital, "assets": {}}
        save_portfolio(new_portfolio); return new_portfolio
    
def save_portfolio(portfolio_data):
    with open('portfolio.json', 'w') as f: json.dump(portfolio_data, f, indent=4)

def init_database():
    conn = sqlite3.connect('trades.db')
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trades (
        timestamp TEXT,
        symbol TEXT,
        action TEXT,
        price REAL,
        amount REAL,
        score REAL,
        regime TEXT,
        character TEXT,
        logic_metadata TEXT
    )
    ''')
    cursor.execute("PRAGMA table_info(trades)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'logic_metadata' not in columns:
        log_analysis("Migrating Database: Adding 'logic_metadata' column...")
        cursor.execute("ALTER TABLE trades ADD COLUMN logic_metadata TEXT")
    conn.commit()
    conn.close()
    log_analysis("Database (trades.db) initialized/verified.")

def record_trade(symbol, action, price, amount, score, market_regime, market_character, logic_dict=None, fee=0.0):    conn = sqlite3.connect('trades.db')
    cursor = conn.cursor()
    logic_json = json.dumps(logic_dict) if logic_dict else "{}"
    cursor.execute('''
INSERT INTO trades (timestamp, symbol, action, price, amount, score, regime, character, logic_metadata, fee)    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        symbol,
        action.upper(),
        price,
        amount,
        float(f"{score:.2f}"), 
        market_regime,
        market_character,
        logic_json, fee
    ))
    conn.commit()
    conn.close()

def log_portfolio_value(timestamp, portfolio_value):
    file_path = 'pnl_history.csv'
    file_exists = os.path.isfile(file_path)
    with open(file_path, 'a', newline='') as csvfile:
        fieldnames = ['timestamp', 'portfolio_value']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow({
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'portfolio_value': f"{portfolio_value:.2f}" 
        })

# --- INDICATOR AND STRATEGY LOGIC ---

def rgb_to_ansi(rgb_list):
    if not isinstance(rgb_list, list) or len(rgb_list) != 3: return ""
    r, g, b = rgb_list
    return f'\033[38;2;{r};{g};{b}m'

def get_symbol_daily_stats(exchange, symbol, config):
    try:
        adx_period = config.get('adx_period', 14)
        adx_threshold = config.get('adx_trending_threshold', 25)
        
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1d', limit=260)
        
        if not ohlcv or len(ohlcv) < 200:
            return "Ranging", 0.0, "neutral", "neutral", 1, 0.0 
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        current_price = df['close'].iloc[-1]

        df.ta.adx(length=adx_period, append=True)
        adx_col = f'ADX_{adx_period}'
        if adx_col in df.columns:
            latest_adx = df[adx_col].iloc[-1]
            character = "Trending" if latest_adx > adx_threshold else "Ranging"
        else:
            character = "Ranging"; latest_adx = 0.0

        df['SMA_50'] = df['close'].rolling(window=50).mean()
        df['SMA_200'] = df['close'].rolling(window=200).mean()
        
        sma_50 = df['SMA_50'].iloc[-1]
        sma_200 = df['SMA_200'].iloc[-1]
        sma_prev_50 = df['SMA_50'].iloc[-2]
        
        if pd.isna(sma_50):
            tactical_regime = "neutral"; slope = 1; sma_50 = 0.0
        else:
            tactical_regime = "bear" if current_price < sma_50 else "bull"
            slope = -1 if sma_50 < sma_prev_50 else 1
            
        if pd.isna(sma_200):
            structural_regime = "neutral"
        else:
            structural_regime = "bear" if current_price < sma_200 else "bull"
        
        return character, latest_adx, tactical_regime, structural_regime, slope, sma_50
        
    except Exception as e:
        log_terminal(f"Error calculating daily stats for {symbol}: {e}")
        return "Ranging", 0.0, "neutral", "neutral", 1, 0.0

def get_global_funding_rate(config):
    if not config.get('funding_monitor', {}).get('enabled', True):
        return 0.0
    try:
        temp_exchange = ccxt.binance() 
        funding_info = temp_exchange.fetch_funding_rate('BTC/USDT')
        rate_percent = funding_info['fundingRate'] * 100 
        return rate_percent
    except Exception:
        return 0.0

def get_percent_change(exchange, symbol, timeframe):
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=2)
        if not ohlcv or len(ohlcv) < 2: return 0
        prev_close = ohlcv[-2][4]
        current_price = ohlcv[-1][4]
        if prev_close == 0: return 0
        return ((current_price - prev_close) / prev_close) * 100
    except Exception:
        return 0

def get_macd_signal(df, config):
    try:
        macd_config = config.get('macd_config', {}); fast, slow, signal = macd_config.get('fast', 12), macd_config.get('slow', 26), macd_config.get('signal', 9)
        df.ta.macd(fast=fast, slow=slow, signal=signal, append=True)
        hist_latest, hist_previous = df[f'MACDh_{fast}_{slow}_{signal}'].iloc[-1], df[f'MACDh_{fast}_{slow}_{signal}'].iloc[-2]
        if hist_latest > 0 and hist_previous < hist_latest: return 1
        elif hist_latest < 0 and hist_previous > hist_latest: return -1
        else: return 0
    except Exception: return 0

def run_mtfa(exchange, symbol, config, market_character):
    if market_character == "Trending": timeframe_weights = config.get('timeframe_weights_trending', {})
    else: timeframe_weights = config.get('timeframe_weights_ranging', {})
    
    mtfa_score = 0.0; latest_rsi = 50.0; prev_rsi = 50.0; macd_score = 0.0; ma_value = 0.0; error_message = None
    latest_volume = 0.0; median_volume = 0.0; target_volume = 0.0; volume_check_passed = False; df_1h = None

    try:
        ohlcv_1h = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        if ohlcv_1h and len(ohlcv_1h) > 50:
            df_1h = pd.DataFrame(ohlcv_1h, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        else:
            raise Exception("Not enough 1h data")
    except Exception as e:
        log_terminal(f"  -> Could not fetch 1h data for {symbol}: {e}")
        return mtfa_score, macd_score, latest_rsi, prev_rsi, ma_value, volume_check_passed, "Error: Data", latest_volume, median_volume, target_volume
        
    for timeframe, weight in timeframe_weights.items():
        mtfa_score += get_percent_change(exchange, symbol, timeframe) * weight; time.sleep(0.1)
        
    if df_1h is not None:
        macd_signal = get_macd_signal(df_1h.copy(), config)
        macd_score = macd_signal * config.get('macd_score_weight', 0.5)
        try:
            rsi_period = config.get('rsi_config', {}).get('period', 14)
            df_1h.ta.rsi(length=rsi_period, append=True)
            rsi_col = f'RSI_{rsi_period}'
            latest_rsi = df_1h[rsi_col].iloc[-1]
            prev_rsi = df_1h[rsi_col].iloc[-2]
            if pd.isna(latest_rsi): latest_rsi = 50.0
            if pd.isna(prev_rsi): prev_rsi = 50.0
        except Exception: error_message = "Error: RSI Calc Failed"
        
        try:
            ma_config = config.get('ma_filter_config', {})
            if ma_config.get('enabled', True):
                ma_period = ma_config.get('period', 20)
                df_1h[f'SMA_{ma_period}'] = df_1h['close'].rolling(window=ma_period).mean()
                ma_value = df_1h[f'SMA_{ma_period}'].iloc[-1]
                if pd.isna(ma_value): ma_value = 0.0
            else: ma_value = 0.0
        except Exception: ma_value = 0.0

    vol_config = config.get('volume_confirmation', {})
    if vol_config.get('enabled', False):
        try:
            vol_tf = vol_config.get('timeframe', '1d') 
            period = vol_config.get('period', 10)
            multiplier = vol_config.get('multiplier', 1.5)
            
            ohlcv_vol = exchange.fetch_ohlcv(symbol, timeframe=vol_tf, limit=100)
            if not ohlcv_vol: raise Exception("No daily volume data")
            
            df_vol = pd.DataFrame(ohlcv_vol, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df_vol['VOL_MEDIAN'] = df_vol['volume'].rolling(window=period).median()
            median_volume = df_vol['VOL_MEDIAN'].iloc[-1]
            if pd.isna(median_volume) or median_volume == 0: raise Exception("Volume Median is NaN")

            if vol_tf == '1d' and df_1h is not None:
                latest_volume = df_1h['volume'].iloc[-24:].sum()
            else:
                latest_volume = df_vol['volume'].iloc[-1]

            target_volume = median_volume * multiplier
            
            if latest_volume > target_volume:
                volume_check_passed = True
                log_analysis(f"  -> Volume Check (Rolling 24h): PASSED (Vol: {latest_volume:.0f} > Target: {target_volume:.0f})")
            else:
                volume_check_passed = False
                log_analysis(f"  -> Volume Check (Rolling 24h): FAILED (Vol: {latest_volume:.0f} <= Target: {target_volume:.0f})")
        except Exception as e:
            log_analysis(f"  -> Could not calculate Volume: {e}"); volume_check_passed = True 
    else:
        volume_check_passed = True

    return mtfa_score, macd_score, latest_rsi, prev_rsi, ma_value, volume_check_passed, error_message, latest_volume, median_volume, target_volume

def get_dynamic_thresholds(config, market_regime):
    # [v2.4 FIX] Uses the passed regime (now Local) to determine difficulty
    buy = config.get('neutral_buy_threshold', 1.5)
    sell = config.get('neutral_sell_threshold', -1.5)
    modifier = config.get('bull_bear_modifier', 0.5)
    
    if market_regime == 'bull': 
        buy -= modifier
        sell -= modifier
    elif market_regime == 'bear': 
        buy += modifier
        sell += modifier
    return buy, sell
    
def format_price(price):
    if price is None: return "N/A"
    if price >= 1.0: return f"${price:.2f}"
    elif price >= 0.01: return f"${price:.4f}"
    else: return f"${price:.6f}"

def format_large_number(num):
    try:
        num = float(num)
        if num >= 1_000_000_000: return f"{num/1_000_000_000:.2f}B"
        if num >= 1_000_000: return f"{num/1_000_000:.2f}M"
        if num >= 1_000: return f"{num/1_000:.2f}K"
        return f"{num:.0f}"
    except:
        return "0"
    
def build_analysis_log(symbol, logic_data, config):
    """
    Constructs a clean, stateless log message for the terminal.
    PRESERVES COLORS from config.
    """
    # 1. Setup Colors
    c_pos = rgb_to_ansi(config.get('colors', {}).get('positive', [46, 204, 113]))
    c_neg = rgb_to_ansi(config.get('colors', {}).get('negative', [231, 76, 60]))
    c_neu = rgb_to_ansi(config.get('colors', {}).get('neutral', [77, 160, 230]))
    c_reset = Style.RESET_ALL

    # 2. Extract Data (Safely)
    price = logic_data.get('price', 0)
    details = logic_data.get('details', {})
    
    # 3. Build String (Fresh every time)
    log_str = f"Analyzing {symbol}\n"
    
    # Price Line
    chg_5m = logic_data.get('change_5m', 0)
    chg_24h = logic_data.get('change_24h', 0)
    col_5m = c_pos if chg_5m >= 0 else c_neg
    col_24h = c_pos if chg_24h >= 0 else c_neg
    log_str += f" -> Current Price:    ${price:.4f} (5m: {col_5m}{chg_5m:.2f}%{c_reset} / 24h: {col_24h}{chg_24h:.2f}%{c_reset})\n"
    
    # Context Variables
    global_reg = str(logic_data.get('market_regime', 'N/A')).upper()
    struct_reg = str(logic_data.get('struct_regime', 'N/A')).upper()
    funding_rate = logic_data.get('funding_rate', 0.0)
    
    # Line 1: Market Regime
    reg_col = c_pos if global_reg == "BULL" else (c_neg if global_reg == "BEAR" else c_neu)
    log_str += f" -> Market Regime:    {reg_col}{global_reg}{c_reset}\n"

    # Line 2: Context (Structure + Funding)
    struct_col = c_pos if struct_reg == "BULL" else (c_neg if struct_reg == "BEAR" else c_neu)
    fund_col = c_neu
    if funding_rate > 0.02: fund_col = c_neg 
    elif funding_rate < 0: fund_col = c_pos 
    log_str += f" -> Macro Context:    Struct: {struct_col}{struct_reg}{c_reset} | Fund: {fund_col}{funding_rate:.4f}%{c_reset}\n"
    
    # Line 3: Strategy & ADX
    strat = logic_data.get('strategy', 'N/A')
    adx_val = details.get('adx')
    if adx_val is not None:
        thresh = config.get('adx_trending_threshold', 25)
        c_adx = c_pos if float(adx_val) > thresh else c_neg
        adx_str = f" (ADX: {c_adx}{float(adx_val):.2f}{c_reset})"
    else:
        adx_str = ""
    log_str += f" -> Active Strategy:  {c_neu}{strat}{c_reset}{adx_str}\n"
    
    # Line 4: Volume
    vol_check = details.get('vol_check', 'N/A')
    # Handle volume numbers (check if they are strings or floats)
    try:
        vol_val = float(details.get('latest_vol', 0))
        tgt_val = float(details.get('target_vol', 0))
    except:
        vol_val = 0; tgt_val = 0
        
    vol_sign = ">" if vol_check == "PASSED" else "<="
    vol_col = c_pos if vol_check == "PASSED" else c_neg
    log_str += f" -> Volume Check:     {vol_col}{vol_check}{c_reset} ({vol_val:,.0f} {vol_sign} Tgt: {tgt_val:,.0f})\n"
    
    # Line 5: MA Filter
    ma_val = logic_data.get('ma_value', 0)
    if ma_val > 0:
        ma_pass = price > ma_val
        ma_sign = ">" if ma_pass else "<"
        ma_res = "PASSED" if ma_pass else "BLOCKED"
        ma_col = c_pos if ma_pass else c_neg
        log_str += f" -> MA Filter:        {ma_col}{ma_res}{c_reset} (Price ${price:.4f} {ma_sign} MA ${ma_val:.4f})\n"
    
    # Line 6: RSI
    rsi = logic_data.get('rsi', 0)
    log_str += f" -> RSI (1h):         {rsi:.2f}\n"

    # Line 7: ATR Stops (If available)
    if details.get('atr_stop'):
        log_str += f" -> ATR Stop Target: < ${float(details.get('atr_stop')):.4f}\n"
    
    # Line 8: Thresholds
    buy_th = logic_data.get('buy_thresh', 0); sell_th = logic_data.get('sell_thresh', 0)
    log_str += f" -> Thresholds:       BUY > {buy_th:.2f} | SELL < {sell_th:.2f}\n"
    
    # Line 9: Score
    score = logic_data.get('score', 0); macd = details.get('macd_score', 0); mtfa = score - macd
    score_col = c_pos if score > 0 else c_neg
    if score == 999:
        log_str += f" -> Score:            {c_neu}999 (Forced Dip Buy){c_reset}\n"
    else:
        log_str += f" -> Score Calc:       MTFA({mtfa:.2f}) + MACD({macd:.2f}) = {score_col}{score:.3f}{c_reset}\n"

    # Line 10: ACTION
    status = logic_data.get('status', 'Idle')
    stat_col = c_neu
    if "BUY" in status or "TAKE" in status: stat_col = c_pos
    elif "SELL" in status or "STOP" in status: stat_col = c_neg
    elif "BLOCKED" in status: stat_col = c_neg # Optional: Make blocked red
    
    log_str += f" -> ACTION:           {stat_col}{status}{c_reset}"
    
    return log_str

# --- CORE LOGIC FLOW ---

def check_price_and_decide(exchange, symbol, config, portfolio, global_regime, global_struct_regime, global_funding_rate, market_character, adx_value, local_regime, local_slope, local_sma, bot_status, event_queue):
    cash_balance = portfolio.get('cash', 0)
    
    # [Dynamic Thresholds]
    buy_threshold, sell_threshold = get_dynamic_thresholds(config, local_regime)
    
    trades_list = portfolio['assets'].get(symbol)
    is_currently_held = True if trades_list else False
    
    # [Winter Protocol]
    winter_mode = (global_struct_regime == 'bear')
    if winter_mode: buy_threshold += 0.5 
    
    status_update = {
        'status': 'Analyzing...', 'price': 0.0, 'change_5m': 0.0, 'change_24h': 0.0, 'pnl': 0.0,
        'entry': 0.0, 'score': 0.0, 'rsi': 0.0,
        'buy_thresh': buy_threshold, 'sell_thresh': sell_threshold, 'is_held': is_currently_held,
        'latest_vol': 0.0, 'median_vol': 0.0, 'target_vol': 0.0,
        'ma_value': 0.0, 'local_sma': local_sma, 'strategy': market_character,
        'cash': cash_balance, 
        'market_regime': global_regime, 
        'struct_regime': global_struct_regime,
        'funding_rate': global_funding_rate,
        'local_regime': local_regime,
        'details': {'adx': adx_value} 
    }
    bot_status['symbols'][symbol] = status_update

    # --- 1. GET PRICE ---
    try:
        ticker = exchange.fetch_ticker(symbol)
        current_price = ticker.get('last')
        status_update['price'] = current_price
        status_update['change_5m'] = get_percent_change(exchange, symbol, '5m')
        status_update['change_24h'] = get_percent_change(exchange, symbol, '1d')
    except Exception as e:
        status_update['status'] = f"Error: No Ticker"
        log_terminal(f"Error fetching {symbol}: {e}")
        return None

    # --- 2. RUN INDICATORS (MTFA) ---
    mtfa_score, macd_score, latest_rsi, prev_rsi, ma_value, volume_check_passed, error, latest_vol, median_vol, target_vol = run_mtfa(exchange, symbol, config, market_character)
    
    if error:
        status_update['status'] = error
        log_terminal(build_analysis_log(symbol, status_update, config))
        return None

    # Populate Status
    status_update['rsi'] = latest_rsi
    status_update['ma_value'] = ma_value
    status_update['details']['macd_score'] = macd_score
    status_update['details']['vol_check'] = "PASSED" if volume_check_passed else "FAILED"
    status_update['details']['latest_vol'] = f"{latest_vol:.0f}"
    status_update['details']['median_vol'] = f"{median_vol:.0f}"
    status_update['details']['target_vol'] = f"{target_vol:.0f}"

    # Calculate Score
    total_score = mtfa_score + macd_score
    # Calculate Heat Score for Dashboard Badge
    # We create a temp dict with the data we have available right now
    heat_data = {'rsi': latest_rsi, 'macd_score': macd_score} 
    heat_score = calculate_heat_score(heat_data)
    
    status_update['advisor_score'] = heat_score
    
    # Adjust Score (Funding/Volume)
    if config.get('funding_monitor', {}).get('enabled', True):
        if global_funding_rate > 0.02: total_score -= 2.0
        elif global_funding_rate < 0: total_score += 1.0

    status_update['score'] = total_score

    # --- 3. PREPARE POSITION DATA (ATR & HWM) ---
    atr_val = 0.0
    hwm = 0.0
    avg_entry = 0.0
    
    # Calculate ATR (Used for Stops AND Dips)
    try:
        atr_stop_config = config.get('atr_stop_loss_config', {})
        # We need ATR regardless of holding status now, for Dip Targets too
        ohlcv_atr = exchange.fetch_ohlcv(symbol, timeframe=atr_stop_config.get('timeframe', '1h'), limit=100)
        df_atr = pd.DataFrame(ohlcv_atr, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_atr.ta.atr(length=14, append=True)
        atr_val = df_atr[f'ATRr_14'].iloc[-1]
    except Exception as e:
        pass # ATR failure shouldn't crash bot, but will disable stops

    if trades_list:
        # High Water Mark Logic
        total_cost = sum(t['cost_basis'] for t in trades_list)
        total_amt = sum(t['amount'] for t in trades_list)
        avg_entry = total_cost / total_amt if total_amt else 0
        
        # Update HWM
        hwm = max(t['high_water_mark'] for t in trades_list)
        if current_price > hwm:
            for t in trades_list: t['high_water_mark'] = current_price
            portfolio['assets'][symbol] = trades_list
            save_portfolio(portfolio)
            hwm = current_price
        
        status_update['entry'] = avg_entry
        status_update['pnl'] = ((current_price - avg_entry)/avg_entry)*100

    # --- 4. STRATEGY DECISION (The Modular Part) ---
    analysis_data = {
        'score': total_score,
        'rsi': latest_rsi,
        'prev_rsi': prev_rsi,
        'market_character': market_character,
        'global_regime': global_regime,
        'local_regime': local_regime,
        'local_slope': local_slope,
        'vol_passed': volume_check_passed,
        'buy_thresh': buy_threshold,
        'sell_thresh': sell_threshold,
        'current_price': current_price,
        'ma_passed': (current_price > ma_value) if ma_value > 0 else True,
        'last_sell_price': portfolio.get('last_sell_prices', {}).get(symbol, {}).get('price'),
        'atr_value': atr_val,
        'high_water_mark': hwm,
        'avg_entry_price': avg_entry
    }
    
    # Calculate Dip Target for Strategy
    if not trades_list and analysis_data['last_sell_price'] and atr_val > 0:
        dip_mult = config.get('dip_buy_atr_multiplier', 1.5)
        analysis_data['dip_target'] = analysis_data['last_sell_price'] - (atr_val * dip_mult)
        status_update['details']['dip_target'] = analysis_data['dip_target']

    # --- CALL THE STRATEGY ---
    action, reason, final_score = STRATEGY_ENGINE.decide_action(config, symbol, analysis_data, trades_list)
    
    status_update['status'] = f"{action} ({reason})"
    if final_score != total_score: status_update['score'] = final_score

    # --- EXECUTE ---
    log_terminal(build_analysis_log(symbol, status_update, config))

    if action == "BUY":
        return {
            "action": "buy", "symbol": symbol, "price": current_price,
            "score": abs(final_score), "market_regime": global_regime, "market_character": market_character,
            "logic_data": status_update 
        }
    elif action == "DIP_BUY":
        status_update['trade_type'] = 'dip'
        return {
            "action": "buy", "symbol": symbol, "price": current_price,
            "score": 999, "market_regime": global_regime, "market_character": market_character,
            "logic_data": status_update 
        }
    elif action == "SELL":
        execute_sell(exchange, symbol, current_price, portfolio, config, global_regime, market_character, event_queue, score=total_score, reason=reason, logic_data=status_update)
        return None
    
    return None

def get_position_size(portfolio, price, symbol, config, score=0):
    """
    Determines trade size based on Active Strategy.
    - Standard: Uses Sizing Tiers & Percentages.
    - Accumulator: Uses Fixed USD Amount ($ Bullets).
    """
    cash = portfolio.get('cash', 0)
    profile = config.get('strategy_profile', 'standard').lower()

    # --- ACCUMULATOR LOGIC (Fixed Bullets) ---
    if profile == 'accumulator':
        # 1. Get Bullet Size
        acc_config = config.get('event_horizon_config', {})
        bullet_size = acc_config.get('accumulator_buy_amount_usd', 250.0)
        
        # 2. Check Cap (Max Allocation)
        current_assets = portfolio['assets'].get(symbol, [])
        current_holdings_cost = sum(t['cost_basis'] for t in current_assets)
        total_port_val = cash + sum(sum(t['cost_basis'] for t in a) for a in portfolio['assets'].values())
        max_alloc = total_port_val * acc_config.get('max_asset_allocation_pct', 0.20)
        
        # If adding this bullet exceeds cap, shrink it or block it
        if (current_holdings_cost + bullet_size) > max_alloc:
             log_terminal(f"⚠️ Sizing Cap: {symbol} is near max allocation.")
             remaining_room = max_alloc - current_holdings_cost
             if remaining_room < 15: return 0.0 # Too small to bother
             bullet_size = remaining_room

        # 3. Final Cash Check
        if bullet_size > cash:
            return 0.0 
            
        return bullet_size / price

    # --- STANDARD LOGIC (Tiers) ---
    else:
        # Use Dynamic Tiers based on Score
        tiers = config.get('sizing_tiers', [[6, 0.25], [3.5, 0.20], [2.1, 0.15], [0.5, 0.10]])
        allocation_pct = 0.05 # Default safety
        
        for tier_score, tier_pct in tiers:
            if score >= tier_score:
                allocation_pct = tier_pct
                break
        
        # Scale down if we already hold it (DCA Scaling)
        if symbol in portfolio['assets']:
            multiplier = config.get('scaling_multiplier', 0.5)
            allocation_pct *= multiplier

        trade_amount_usd = cash * allocation_pct
        
        # Minimum Trade Size Check
        min_usd = config.get('min_trade_size_usd', 15)
        if trade_amount_usd < min_usd:
            return 0.0

        return trade_amount_usd / price    

def execute_buy(exchange, symbol, price, config, portfolio, score, market_regime, market_character, event_queue, logic_data=None):
    cash_balance = portfolio.get('cash', 0)
    low_funds_reserve = config.get('low_funds_threshold', 10.0)
    min_trade_size = config.get('min_trade_size', 10.0)

    trade_type = 'standard'
    if logic_data and 'trade_type' in logic_data:
        trade_type = logic_data.get('trade_type')
    
    usable_cash = cash_balance - low_funds_reserve
    if usable_cash < min_trade_size:
        log_terminal(f"  -> Skipping buy, usable cash (${usable_cash:.2f}) is below min_trade_size.")
        return

    # --- 1. Global Portfolio Exposure Check ---
    current_invested_value = 0.0
    symbol_invested_value = 0.0 # [NEW] Track specific symbol value
    
    for asset_sym, asset_trades in portfolio['assets'].items():
        asset_val = sum(t.get('cost_basis', 0.0) for t in asset_trades)
        current_invested_value += asset_val
        if asset_sym == symbol:
            symbol_invested_value = asset_val

    total_portfolio_value = cash_balance + current_invested_value
    current_exposure = current_invested_value / total_portfolio_value if total_portfolio_value > 0 else 0
    max_exposure = config.get('max_portfolio_exposure', 1.0)

    if current_exposure >= max_exposure:
        log_terminal(f"  🚫 MAX EXPOSURE REACHED: {current_exposure:.1%} >= Limit {max_exposure:.1%}.")
        return 

    # --- 2. Calculate Base Size ---
    if score == 999:
        log_terminal(f"  -> Dip-Buy signal detected.")
        allocation_percent = config.get('dip_buy_allocation_percent', 0.10) 
        strategy_name = "ATR Dip-Buy"
    else:
        sizing_tiers = config.get('sizing_tiers', [])
        allocation_percent = 0
        for tier in sorted(sizing_tiers, key=lambda x: x[0], reverse=True):
            if score >= tier[0]:
                allocation_percent = tier[1]; break
        strategy_name = "Momentum" if market_character == "Trending" else "Buy the Dip"

    if allocation_percent == 0:
        log_terminal(f"  -> Score {score:.2f} is below minimum sizing tier."); return

    cash_to_use = usable_cash * allocation_percent

    # --- 3. Scaling Logic & Single Asset Cap ---
    is_held = (symbol_invested_value > 0)
    scaling_allowed = config.get('allow_scaling_in', False)

    if is_held:
        if not scaling_allowed:
            log_terminal(f"  -> Skipping: Position for {symbol} exists (Scaling Disabled).")
            return
        
        # [CONTROL #1] The Scaling Multiplier
        # Reduce size if we are "Eaasing In"
        scale_mult = config.get('scaling_multiplier', 0.5) 
        cash_to_use = cash_to_use * scale_mult
        log_terminal(f"  -> Scaling In: Reducing size by {100-(scale_mult*100):.0f}% for safety.")

    # [CONTROL #2] Single Asset Exposure Cap
    max_single_exposure = config.get('max_single_position_exposure', 0.25) # Default 25% if missing
    current_symbol_exposure = symbol_invested_value / total_portfolio_value if total_portfolio_value > 0 else 0
    
    # Calculate how much room is left for THIS symbol
    max_allowed_for_symbol = total_portfolio_value * max_single_exposure
    room_remaining = max_allowed_for_symbol - symbol_invested_value
    
    if room_remaining <= 0:
         log_terminal(f"  🚫 SINGLE ASSET CAP: {symbol} is {current_symbol_exposure:.1%} of portfolio (Limit {max_single_exposure:.1%}).")
         return
         
    # Cap the trade if it exceeds the room remaining
    if cash_to_use > room_remaining:
        log_terminal(f"  ⚠️ Capping trade size to ${room_remaining:.2f} to respect {max_single_exposure:.1%} limit.")
        cash_to_use = room_remaining

    # ---------------------------------------------

    # Final Checks
    if cash_to_use > usable_cash: cash_to_use = usable_cash
    if cash_to_use < min_trade_size:
        log_terminal(f"  -> Skipping buy, final size (${cash_to_use:.2f}) below min trade.")
        return
    
    # --- Execution ---
    fee_percent = config.get('fees', {}).get('taker_percent', 0.6) / 100
    estimated_fee = cash_to_use * fee_percent
    cash_after_fee = cash_to_use - estimated_fee
    amount_to_buy = cash_after_fee / price 
    
    if config.get("live_trading", False) == True:
        try:
            open_orders = exchange.fetch_open_orders(symbol)
            if open_orders:
                log_terminal(f"  ⚠️ SAFETY SKIP: Open orders found for {symbol}.")
                return

            log_terminal(f"  ⚡ LIVE BUY ({strategy_name}): Spending ${cash_to_use:.2f} on {symbol}")
            order = exchange.create_market_buy_order_with_cost(symbol, cash_to_use)
            real_amount = order.get('filled', amount_to_buy); real_price = order.get('price', price)
            real_cost = order.get('cost', cash_to_use)
            
            log_terminal(f"  ✅ BUY EXECUTED: {real_amount:.6f} {symbol} @ {format_price(real_price)}")
            log_event(f"LIVE BUY: {symbol} @ {format_price(real_price)}", "buy")
            
            new_trade = {'amount': real_amount, 'entry_price': real_price, 'high_water_mark': real_price, 'cost_basis': real_cost, 'trade_type': trade_type}
            trades_list = portfolio['assets'].get(symbol, []); trades_list.append(new_trade)
            portfolio['assets'][symbol] = trades_list
            if portfolio.get('last_sell_prices', {}).get(symbol): del portfolio['last_sell_prices'][symbol]
            save_portfolio(portfolio)
            record_trade(symbol, 'buy', real_price, real_amount, score, market_regime, market_character, logic_data)
        except Exception as e:
            log_terminal(f"  ❌ LIVE BUY FAILED: {e}")
    else:
        log_event(f"GHOST BUY: {amount_to_buy:.6f} {symbol}", "buy")
        positive_color = rgb_to_ansi(config.get('colors', {}).get('positive'))
        log_terminal(f"{positive_color}  -> SIMULATING BUY: {amount_to_buy:.6f} {symbol} for ${cash_to_use:.2f}{Style.RESET_ALL}")
        portfolio['cash'] -= cash_to_use
        new_trade = {'amount': amount_to_buy, 'entry_price': price, 'high_water_mark': price, 'cost_basis': cash_to_use}
        trades_list = portfolio['assets'].get(symbol, []); trades_list.append(new_trade)
        portfolio['assets'][symbol] = trades_list
        if portfolio.get('last_sell_prices', {}).get(symbol): del portfolio['last_sell_prices'][symbol]
        save_portfolio(portfolio)
        record_trade(symbol, 'buy', price, amount_to_buy, score, market_regime, market_character, logic_data)

def execute_sell(exchange, symbol, price, portfolio, config, market_regime, market_character, event_queue, score=0, reason="", logic_data=None):
    accumulator_mode = config.get('accumulator_mode', False) 

    if accumulator_mode:
        logging.info(f"🛡️ ACCUMULATOR MODE: Sell signal for {symbol} suppressed.")
        # Optional: You might want to return 'False' or just return to exit
        return False
    trades_list = portfolio['assets'].get(symbol)
    if not trades_list: 
        log_terminal(f"  -> Tried to sell {symbol} but no position in portfolio.json.")
        return
    total_amount_to_sell = sum(trade['amount'] for trade in trades_list)
    if not reason: reason = f"MTFA Signal (Score: {score:.2f})"

    if config.get("live_trading", False) == True:
        try:
            open_orders = exchange.fetch_open_orders(symbol)
            if open_orders:
                log_terminal(f"  ⚠️ SAFETY SKIP: Open orders found for {symbol}. Waiting for exchange to fill/cancel.")
                log_event(f"SAFETY SKIP: Open orders exist for {symbol}", "warning")
                return

            log_terminal(f"  ⚡ ATTEMPTING LIVE SELL: {total_amount_to_sell:.6f} {symbol}")
            real_balance = exchange.fetch_balance()
            base_currency = symbol.split('/')[0] 
            amount_on_exchange = real_balance[base_currency]['free']
            if amount_on_exchange < total_amount_to_sell * 0.9: 
                 raise Exception(f"Portfolio mismatch! portfolio.json says we have {total_amount_to_sell} but exchange says {amount_on_exchange}")
            
            order = exchange.create_market_sell_order(symbol, amount_on_exchange)
            real_amount = order.get('filled', amount_on_exchange)
            real_price = order.get('price', price)
            log_terminal(f"  ✅ LIVE SELL EXECUTED: {real_amount:.6f} {symbol} at ~{format_price(real_price)}")
            log_event(f"LIVE SELL: {real_amount:.6f} {symbol} at {format_price(real_price)} (Reason: {reason})", "sell")
            del portfolio['assets'][symbol]
            if 'last_sell_prices' not in portfolio: portfolio['last_sell_prices'] = {}
            portfolio['last_sell_prices'][symbol] = {'price': real_price}
            save_portfolio(portfolio)
            record_trade(symbol, 'sell', real_price, real_amount, score, market_regime, market_character, logic_data)
        except Exception as e:
            log_terminal(f"  ❌ LIVE SELL FAILED: {e}")
            log_event(f"LIVE SELL FAILED for {symbol}: {e}", "error")
    else:
        revenue = total_amount_to_sell * price
        fee_percent = config.get('fees', {}).get('taker_percent', 0.6) / 100
        fee = revenue * fee_percent
        revenue_after_fee = revenue - fee
        log_event(f"GHOST SELL: {total_amount_to_sell:.6f} {symbol} at {format_price(price)} (Reason: {reason})", "sell")
        log_terminal(f"  -> SIMULATING SELL of entire position: {total_amount_to_sell:.6f} {symbol} for ${revenue:.2f} (Taker Fee: ${fee:.2f})")
        portfolio['cash'] += revenue_after_fee
        del portfolio['assets'][symbol]
        if 'last_sell_prices' not in portfolio: portfolio['last_sell_prices'] = {}
        portfolio['last_sell_prices'][symbol] = {'price': price}
        save_portfolio(portfolio)
        record_trade(symbol, 'sell', price, total_amount_to_sell, score, market_regime, market_character, logic_data)

def calculate_heat_score(current_data):
    """
    Calculates a 0-100 'Heat Score' for Accumulator Mode.
    """
    try:
        score = 0
        
        # 1. RSI Heat
        rsi = current_data.get('rsi', 50)
        if rsi >= 70: score += 40
        elif rsi >= 60: score += 20
        elif rsi >= 50: score += 10
            
        # 2. MACD Heat
        macd_hist = current_data.get('macd_hist', 0)
        if macd_hist < 0: score += 20
        elif macd_hist < 5: score += 10
            
        # Cap at 100
        return int(min(100, max(0, score)))

    except Exception as e:
        print(f"Error calculating Heat Score: {e}")
        return 0

def force_sell_position(symbol):
    """ Manually sells 100% of a position immediately. """
    try:
        # 1. LOAD CONFIG FIRST (Because load_portfolio needs it)
        try:
            config = load_config()
        except NameError:
            with open('config.json', 'r') as f: config = json.load(f)

        # 2. LOAD PORTFOLIO (Passing config)
        try:
            portfolio = load_portfolio(config) # <--- FIXED: Added config argument
        except NameError:
            with open('portfolio.json', 'r') as f: portfolio = json.load(f)
        except TypeError: 
            # Fallback if your specific load_portfolio doesn't actually take config
            # (Safety catch for different code versions)
            portfolio = load_portfolio() 

        # 3. VERIFY HOLDING
        if symbol not in portfolio.get('assets', {}):
            return {"status": "error", "message": f"Symbol {symbol} not found in portfolio."}

        trades = portfolio['assets'][symbol]
        total_amount = sum(t['amount'] for t in trades)
        
        if total_amount <= 0:
            return {"status": "error", "message": "Holding amount is 0."}

        # 4. SETUP & GET PRICE
        live_trading = config.get('live_trading', False)
        
        # Initialize exchange for ticker/selling
        # Use helper if available, otherwise manual
        try:
            exchange = initialize_exchange(config)
        except NameError:
            # Fallback for manual init if helper missing (requires ccxt)
            import ccxt
            exchange_class = getattr(ccxt, config.get('exchange_id', 'coinbase'))
            exchange = exchange_class({
                'apiKey': config['api_key'],
                'secret': config['api_secret'],
            })

        try:
            ticker = exchange.fetch_ticker(symbol)
            current_price = ticker['last']
        except:
            current_price = 0.0

        # 5. EXECUTE SELL
        if live_trading:
            # --- LIVE MODE ---
            try:
                order = exchange.create_market_sell_order(symbol, total_amount)
                log_terminal(f"💥 MANUAL FORCE SELL: Sold {total_amount} {symbol} on Coinbase!")
            except Exception as e:
                return {"status": "error", "message": f"Coinbase Error: {str(e)}"}
        else:
            # --- GHOST MODE ---
            log_terminal(f"👻 GHOST FORCE SELL: Simulating sale of {total_amount} {symbol} @ ${current_price}")

        # 6. RECORD TO TRADES.DB
        try:
            conn = sqlite3.connect('trades.db')
            cursor = conn.cursor()
            
            logic_meta = json.dumps({
                "strategy": "MANUAL_FORCE_SELL", 
                "reason": "User clicked Liquidate button",
                "mode": "LIVE" if live_trading else "GHOST"
            })
            
            cursor.execute('''
                INSERT INTO trades (timestamp, symbol, action, price, amount, score, regime, character, logic_metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                symbol,
                "SELL",
                current_price,
                total_amount,
                -999,
                "MANUAL",
                "MANUAL",
                logic_meta
            ))
            conn.commit()
            conn.close()
            log_terminal("📝 Trade recorded to trades.db")
        except Exception as e:
            log_terminal(f"⚠️ Failed to write to DB: {e}")

        # 7. UPDATE PORTFOLIO
        if symbol in portfolio['assets']:
            del portfolio['assets'][symbol]
        
        if 'last_sell_prices' in portfolio and symbol in portfolio['last_sell_prices']:
             del portfolio['last_sell_prices'][symbol]

        # 8. SAVE PORTFOLIO
        try:
            save_portfolio(portfolio)
        except NameError:
             with open('portfolio.json', 'w') as f:
                json.dump(portfolio, f, indent=4)
        
        return {"status": "success", "message": f"Liquidated {total_amount} {symbol}"}

    except Exception as e:
        print(f"Force Sell Failed: {e}")
        return {"status": "error", "message": str(e)}

def check_and_sweep_profits(exchange, config, portfolio, event_queue):
    sweep_config = config.get('profit_sweeping', {})
    if not sweep_config.get('enabled', False): return
    start_cap = config.get('starting_capital', 10000.0)
    threshold = sweep_config.get('sweep_threshold', 500.0)
    buffer = sweep_config.get('keep_buffer', 0.0)
    asset_to_buy = sweep_config.get('asset_to_buy', 'USDC/USD')
    current_cash = portfolio.get('cash', 0.0)
    excess_cash = current_cash - (start_cap + threshold + buffer)
    
    if excess_cash > 10.0: 
        log_terminal(f"💰 Profit Sweep Triggered! Excess Cash: ${excess_cash:.2f}")
        usdc_price = 1.0 
        if config.get("live_trading", False):
            try:
                order = exchange.create_market_buy_order_with_cost(asset_to_buy, excess_cash)
                real_cost = order.get('cost', excess_cash)
                real_amount = order.get('filled', excess_cash / usdc_price)
                log_event(f"VAULT SWEEP: Secured ${real_cost:.2f} into {asset_to_buy}", "success")
                portfolio['cash'] -= real_cost
                record_trade(asset_to_buy, 'SWEEP', usdc_price, real_amount, 0, 'N/A', 'Vault', {'type': 'sweep'})
            except Exception as e:
                log_terminal(f"❌ Profit Sweep Failed: {e}")
                log_event(f"Profit Sweep Failed: {e}", "error")
        else:
            log_event(f"GHOST SWEEP: Secured ${excess_cash:.2f} into {asset_to_buy}", "success")
            portfolio['cash'] -= excess_cash
            amount_swept = excess_cash / usdc_price
            record_trade(asset_to_buy, 'SWEEP', usdc_price, amount_swept, 0, 'N/A', 'Vault', {'type': 'sweep'})
        save_portfolio(portfolio)

def get_current_vault_value(exchange, config):
    sweep_asset = config.get('profit_sweeping', {}).get('asset_to_buy', 'USDC/USD')
    vault_val = 0.0
    if config.get('live_trading', False):
        try:
            base_currency = sweep_asset.split('/')[0] 
            balance = exchange.fetch_balance()
            qty = balance.get(base_currency, {}).get('total', 0.0)
            vault_val = qty * 1.0 
        except Exception: pass
    else:
        try:
            conn = sqlite3.connect('trades.db')
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(amount) FROM trades WHERE symbol = ? AND action = 'SWEEP'", (sweep_asset,))
            result = cursor.fetchone()[0]
            if result: vault_val = result * 1.0
            conn.close()
        except Exception: pass
    return vault_val

def load_config():
    try:
        with open('config.json', 'r') as f: config = json.load(f)
        
        # --- V3 OPEN SOURCE ARCHITECTURE ---
        # We use a dedicated coinbase_keys.json for the multiline ECDSA private key.
        try:
            with open('coinbase_keys.json', 'r') as key_file:
                keys = json.load(key_file)
                config['api_key'] = keys.get('name')
                config['api_secret'] = keys.get('privateKey')
        except FileNotFoundError:
            log_analysis("❌ Error: coinbase_keys.json not found. Please create it from the template.")
            return None
            
        if not config['api_key'] or not config['api_secret']:
            log_analysis("❌ Error: 'name' or 'privateKey' missing in coinbase_keys.json.")
            return None
        return config
    except FileNotFoundError as e:
        log_analysis(f"❌ Error: Configuration file missing: {e.filename}")
        return None
    except json.JSONDecodeError:
        log_analysis("❌ Error: Could not decode a JSON file. Check for syntax errors.")
        return None

def find_top_movers(exchange, config):
    try:
        scanner_config = config.get('dynamic_symbols_config', {})
        top_n = scanner_config.get('top_n_symbols', 10)
        quote_currency = scanner_config.get('quote_currency', 'USD')
        scanner_mode = scanner_config.get('scanner_mode', 'VOLATILITY')
        markets = exchange.fetch_markets()
        config_blacklist = scanner_config.get('blacklist', [])
        safety_blacklist = ['NOM/USD', 'USDT/USD', 'USDC/USD', 'DAI/USD', 'WBTC/USD', 'PYUSD/USD']
        total_blacklist = set(config_blacklist + safety_blacklist + list(RUNTIME_BLACKLIST))
        symbols = [m['symbol'] for m in markets if m['quote'] == quote_currency and m['active'] and 'USD:' not in m['symbol'] and m['symbol'] not in total_blacklist]
        if not symbols: return []
        tickers = {}
        try:
            tickers = exchange.fetch_tickers(symbols)
        except Exception as e:
            log_terminal(f"⚠️ Scanner Batch Failed ({e}). Switch to Single-Fetch Mode to isolate bad coin...")
            for sym in symbols:
                try:
                    t = exchange.fetch_ticker(sym)
                    tickers[sym] = t
                except Exception as inner_e:
                    log_terminal(f"  🚫 BAD COIN DETECTED: {sym}. Adding to Runtime Blacklist.")
                    RUNTIME_BLACKLIST.add(sym)
        scored_symbols = []
        for symbol, ticker in tickers.items():
            if not ticker: continue
            if scanner_mode == 'GAINERS':
                if 'change' in ticker and ticker['change'] is not None:
                    scored_symbols.append((symbol, ticker['change']))
            else:
                last = ticker.get('last')
                quote_vol = ticker.get('quoteVolume')
                base_vol = ticker.get('baseVolume')
                if (quote_vol is None or quote_vol == 0) and (base_vol and last): quote_vol = base_vol * last
                if not (last and quote_vol) or quote_vol < 100000: continue
                high = ticker.get('high')
                low = ticker.get('low')
                if high and low and low > 0:
                    volatility_pct = ((high - low) / low) * 100
                    score = volatility_pct * math.log(quote_vol)
                else:
                    score = math.log(quote_vol)
                scored_symbols.append((symbol, score))
        sorted_symbols = sorted(scored_symbols, key=lambda x: x[1], reverse=True)
        final_list = [s[0] for s in sorted_symbols[:top_n]]
        return final_list
    except Exception as e:
        log_terminal(f"Critical Scanner Error: {e}")
        return []

# --- V3 DATA INTELLIGENCE: CYCLE RECORDER ---
def save_cycle_log(symbol, bot_status, signal, market_character):
    """
    Appends a snapshot of the bot's brain to a CSV file.
    Captures: Price, Indicators, Score, and the Decision (Action).
    """
    log_dir = "data/history_logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # File per symbol (e.g., data/history_logs/BTC-USD.csv)
    safe_symbol = symbol.replace('/', '-')
    filename = f"{log_dir}/{safe_symbol}.csv"
    
    # Extract Data from the shared status (The "Brain")
    symbol_data = bot_status.get('symbols', {}).get(symbol, {})
    details = symbol_data.get('details', {})
    
    # Determine Action
    action = "HOLD"
    if signal:
        action = signal.get('action', 'HOLD').upper()
    
    # Prepare Row Data
    row_data = {
        'Timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'Price': symbol_data.get('price', 0),
        'Action': action,
        'Score': symbol_data.get('score', 0),
        'RSI': details.get('rsi', 0),
        'ADX': details.get('adx', 0),
        'Trend_Slope': details.get('slope', 0),
        'Strategy': market_character,
        'Status_Msg': symbol_data.get('status', '')
    }
    
    # Write to CSV
    file_exists = os.path.isfile(filename)
    with open(filename, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row_data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row_data)
    
def start_bot_logic(bot_status, log_queue, event_queue):
    global stop_requested, GLOBAL_EVENT_QUEUE, GLOBAL_LOG_QUEUE
    GLOBAL_EVENT_QUEUE = event_queue
    GLOBAL_LOG_QUEUE = log_queue
    stop_requested = False 
    log_analysis("🚀 Meta-Strategy Trading Bot Started...")
    init_database()
    config = load_config()
    if not config: log_terminal("Halting."); return
    try:
        exchange = ccxt.coinbase({'apiKey': config.get('api_key'), 'secret': config.get('api_secret')})
        exchange.check_required_credentials()
    except ccxt.AuthenticationError:
        log_terminal("🔑 Authentication failed."); return
    except Exception as e:
        log_terminal(f"An error occurred during exchange setup: {e}"); return
    log_analysis("✅ Successfully connected to the exchange.")
    warmup_cycles_ran = 0

    load_strategy_engine(config)

    while not stop_requested:
        try:
            config = load_config()
            if not config: log_terminal("Config failed to load. Stopping bot."); break
            
            # =====================================================================
            # 🔒 LIVE TRADING OVERRIDE — DISABLED FOR OPEN-SOURCE RELEASE
            # The UI toggle still exists but is forcibly overridden here.
            # Fix it at your own risk.
            # =====================================================================
            IS_LIVE_TRADING = False  # FORCED GHOST MODE
            # IS_LIVE_TRADING = config.get("live_trading", False)  # ORIGINAL
            if IS_LIVE_TRADING:
                try:
                    real_balance = exchange.fetch_balance()
                    current_cash = real_balance['USD']['free']
                    portfolio = load_portfolio(config) 
                    portfolio['cash'] = current_cash
                except Exception as e:
                    log_terminal(f"❌ FATAL: Could not fetch live portfolio: {e}"); break
            else:
                portfolio = load_portfolio(config)
                current_cash = portfolio.get('cash', 0)
            if original_stdout: original_stdout.write("\n--- Starting New Cycle ---\n")
            log_analysis("--- Starting New Cycle ---")
            scanner_config = config.get('dynamic_symbols_config', {})
            if scanner_config.get('enabled', False):
                held_assets = list(portfolio.get('assets', {}).keys())
                top_movers = find_top_movers(exchange, config)
                symbol_list = list(set(held_assets + top_movers))
            else:
                symbol_list = config.get('symbol_list', [])
            if not symbol_list:
                log_terminal("No symbols to analyze. Waiting for next cycle.")
                for _ in range(300):
                    if stop_requested: break
                    time.sleep(1)
                if stop_requested: break
                continue
            if 'symbols' not in bot_status: bot_status['symbols'] = {}
            for symbol in symbol_list:
                if symbol not in bot_status['symbols']:
                    bot_status['symbols'][symbol] = {'status': 'Waiting...', 'price': 0, 'pnl': 0, 'score': 0, 'details': {}}
                else:
                    bot_status['symbols'][symbol]['status'] = "Pending..."
            
            global_funding_rate = get_global_funding_rate(config)
            
            index_symbol = config.get('market_regime_index', 'BTC/USD')
            global_char, global_adx, global_regime, global_struct_regime, global_slope, global_sma = get_symbol_daily_stats(exchange, index_symbol, config)
            
            # [v2.4 UPDATE] Use generic/Global for the dashboard display only, 
            # but decision engine uses Local.
            current_buy_thresh, current_sell_thresh = get_dynamic_thresholds(config, global_regime)
            
            old_portfolio_value = bot_status.get('global', {}).get('portfolio_value', current_cash)
            warmup_cycles_ran += 1
            warmup_config = config.get('warmup_config', {'enabled': False, 'cycles': 3})
            is_warming_up = warmup_config.get('enabled', False) and warmup_cycles_ran <= warmup_config.get('cycles', 3)
            warmup_status_string = f"WARM-UP {warmup_cycles_ran}/{warmup_config.get('cycles', 3)}" if is_warming_up else "Active"
            if is_warming_up: log_terminal(f"--- {warmup_status_string} ---")
            bot_status.setdefault('global', {}).update({
                'countdown': 0, 'portfolio_value': old_portfolio_value, 'cash': current_cash,
                'is_live': IS_LIVE_TRADING, 'warmup_status': warmup_status_string,
                'buy_thresh': current_buy_thresh, 'sell_thresh': current_sell_thresh,
                'market_regime': global_regime, 'market_character': global_char, 'adx_value': global_adx
            })
            log_terminal(f"Symbols to analyze this cycle: {symbol_list}")
            if original_stdout: original_stdout.write("\n")
            potential_buys = []
            trending_count = 0; total_scanned = 0
            for symbol in symbol_list:
                if stop_requested: log_terminal("--- Stop signal received during symbol analysis. ---"); break 
                
                market_character, local_adx, local_regime, local_struct_regime, local_slope, local_sma = get_symbol_daily_stats(exchange, symbol, config)
                
                total_scanned += 1
                if market_character == 'Trending': trending_count += 1
                if symbol in bot_status['symbols']:
                    bot_status['symbols'][symbol]['details']['adx'] = local_adx
                    bot_status['symbols'][symbol]['strategy'] = market_character
                
                signal = check_price_and_decide(exchange, symbol, config, portfolio, 
                                                global_regime, global_struct_regime, global_funding_rate,
                                                market_character, local_adx, local_regime, local_slope, local_sma, 
                                                bot_status, event_queue)              
                save_cycle_log(symbol, bot_status, signal, market_character)
                if signal and signal.get('action') == 'buy': potential_buys.append(signal)
                breadth_msg = f"{trending_count}/{total_scanned} Trending"
                bot_status['global']['character'] = breadth_msg
                if original_stdout: original_stdout.write("\n")
                time.sleep(0.5) 
                if stop_requested: break
            if potential_buys:
                if is_warming_up:
                    log_terminal(" -> Buy signals found, but ignored due to warm-up period.")
                else:
                    positive_color = rgb_to_ansi(config.get('colors', {}).get('positive'))
                    log_terminal(f"\n{positive_color}--- Executing Buy Orders ---{Style.RESET_ALL}")
                    cash_balance = portfolio.get('cash', 0) 
                    low_funds_threshold = config.get('low_funds_threshold', 1000.0)
                    if cash_balance < low_funds_threshold and len(potential_buys) > 1:
                        log_terminal(f" -> Low funds detected. Prioritizing best signal.")
                        best_buy = sorted(potential_buys, key=lambda x: x['score'], reverse=True)[0]
                        execute_buy(exchange, best_buy['symbol'], best_buy['price'], config, portfolio, best_buy['score'], best_buy['market_regime'], best_buy['market_character'], event_queue, logic_data=best_buy.get('logic_data'))
                    else:
                        log_terminal(f"{positive_color} -> Sufficient funds. Executing all valid signals.{Style.RESET_ALL}")
                        for buy_signal in potential_buys:
                            if stop_requested: break 
                            if IS_LIVE_TRADING:
                                try: portfolio['cash'] = exchange.fetch_balance()['USD']['free']
                                except: pass
                            else: portfolio = load_portfolio(config)
                            execute_buy(exchange, buy_signal['symbol'], buy_signal['price'], config, portfolio, buy_signal['score'], buy_signal['market_regime'], buy_signal['market_character'], event_queue, logic_data=buy_signal.get('logic_data'))
            if stop_requested: break
            check_and_sweep_profits(exchange, config, portfolio, event_queue)
            vault_symbol = config.get('profit_sweeping', {}).get('asset_to_buy', 'USDC/USD')
            total_asset_value = 0
            for symbol, trades_list in portfolio.get('assets', {}).items():
                if symbol == vault_symbol: continue
                if symbol in bot_status['symbols'] and bot_status['symbols'][symbol].get('price'):
                    total_amount = sum(trade['amount'] for trade in trades_list)
                    current_price = bot_status['symbols'][symbol].get('price', 0)
                    total_asset_value += total_amount * current_price
            current_vault_value = get_current_vault_value(exchange, config)
            if IS_LIVE_TRADING:
                try:
                    real_balance = exchange.fetch_balance()
                    current_cash = real_balance['USD']['free']
                    portfolio['cash'] = current_cash
                except: pass
            else:
                current_cash = portfolio.get('cash', 0.0) 
            total_portfolio_value = current_cash + total_asset_value + current_vault_value
            bot_status.setdefault('global', {}).update({
                'portfolio_value': total_portfolio_value, 'cash': current_cash, 'vault_value': current_vault_value 
            })
            log_portfolio_value(datetime.now(), total_portfolio_value)
            for symbol in bot_status.get('symbols', {}):
                if "Analyzing" in bot_status['symbols'][symbol].get('status', ''):
                    bot_status['symbols'][symbol]['status'] = "Idle"
            if stop_requested:
                log_terminal("--- Stop signal received before sleep. ---")
                break
            interval_settings = config.get('check_interval_seconds', {})
            sleep_duration = interval_settings.get(global_char.lower(), 300)
            msg = f"--- Cycle complete. Market {global_char} ({global_adx:.2f}). Sleeping {sleep_duration}s ---"
            if original_stdout: original_stdout.write(f"\n{msg}\n")
            log_analysis(msg)
            for i in range(sleep_duration, 0, -1):
                if stop_requested: log_terminal("--- Stop signal received during sleep. Exiting early. ---"); break
                bot_status['global']['countdown'] = i
                time.sleep(1)
            if stop_requested: break
        except Exception as e:
            log_terminal(f"ERROR in main loop: {e}")
            log_terminal("Waiting 60 seconds before retrying...")
            for _ in range(60):
                if stop_requested: break
                time.sleep(1)
    log_terminal("--- Trading bot loop has stopped. ---")

if __name__ == "__main__":
    log_terminal("--- Running trading_bot.py directly for testing ---")
    test_status = {}
    test_log_queue = queue.Queue()
    test_event_queue = queue.Queue()
    def log_printer():
        while True:
            try:
                msg = test_log_queue.get(timeout=1)
                if msg is None: break
                print(msg)
            except queue.Empty:
                if not printer_thread.is_alive(): break
    printer_thread = threading.Thread(target=log_printer, daemon=True)
    printer_thread.start()
    try: start_bot_logic(test_status, test_log_queue, test_event_queue)
    except KeyboardInterrupt: log_terminal("--- Manual stop detected ---"); stop_requested = True
    test_log_queue.put(None); printer_thread.join()

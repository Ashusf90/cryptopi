import ccxt
import json
import pandas as pd
import numpy as np
from colorama import init, Style
import sys, io, queue, threading
from datetime import datetime
import sqlite3
import time
import os

# --- Helper functions ---
def rgb_to_ansi(rgb_list):
    if not isinstance(rgb_list, list) or len(rgb_list) != 3: return ""
    r, g, b = rgb_list
    return f'\033[38;2;{r};{g};{b}m'
    
def colorize_number(number, config, decimals=2, prefix="", suffix=""):
    colors = config.get('colors', {})
    positive_rgb = colors.get('positive', [0, 255, 0])
    negative_rgb = colors.get('negative', [255, 0, 0])
    color_code = rgb_to_ansi(positive_rgb) if number >= 0 else rgb_to_ansi(negative_rgb)
    return f"{color_code}{prefix}{number:.{decimals}f}{suffix}{Style.RESET_ALL}"

def format_price(price):
    if price >= 1.0: return f"${price:.2f}"
    elif price >= 0.01: return f"${price:.4f}"
    else: return f"${price:.6f}"

def load_config():
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
        # Try loading keys if they exist, but don't crash if missing (for simulation)
        if os.path.exists('coinbase_keys.json'):
            with open('coinbase_keys.json', 'r') as f:
                keys = json.load(f)
            config['api_key'] = keys.get('name')
            config['api_secret'] = keys.get('privateKey')
        return config
    except Exception as e:
        print(f"Error loading configuration files: {e}")
        return None

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
        cursor.execute("ALTER TABLE trades ADD COLUMN logic_metadata TEXT")
    conn.commit()
    conn.close()

# --- Advanced Metrics Engine ---
def calculate_advanced_metrics(trades_df, pnl_history_data):
    metrics = {
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "max_drawdown": 0.0,
        "total_trades": 0,
        "avg_win": 0.0,
        "avg_loss": 0.0
    }

    # FIFO Trade Reconstruction
    holdings = {} 
    closed_trades_pnl = []
    
    if not trades_df.empty:
        trades_df = trades_df.sort_values('timestamp')
        
        for index, row in trades_df.iterrows():
            sym = row['symbol']
            action = row['action'].upper()
            price = row['price']
            amount = row['amount']
            
            if action == 'BUY':
                if sym not in holdings: holdings[sym] = []
                holdings[sym].append({'price': price, 'amount': amount})
                
            elif action == 'SELL':
                if sym in holdings and holdings[sym]:
                    cost_basis = 0.0
                    sell_amt_remaining = amount
                    
                    # FIFO Matching
                    while sell_amt_remaining > 0 and holdings[sym]:
                        match_buy = holdings[sym][0]
                        
                        if match_buy['amount'] <= sell_amt_remaining:
                            cost_basis += match_buy['price'] * match_buy['amount']
                            sell_amt_remaining -= match_buy['amount']
                            holdings[sym].pop(0)
                        else:
                            cost_basis += match_buy['price'] * sell_amt_remaining
                            match_buy['amount'] -= sell_amt_remaining
                            sell_amt_remaining = 0
                            
                    revenue = price * amount
                    if amount > 0:
                        trade_pnl = revenue - cost_basis
                        closed_trades_pnl.append(trade_pnl)

    # Calculate Trade Metrics
    if closed_trades_pnl:
        wins = [p for p in closed_trades_pnl if p > 0]
        losses = [p for p in closed_trades_pnl if p <= 0]
        
        metrics['total_trades'] = len(closed_trades_pnl)
        metrics['win_rate'] = (len(wins) / len(closed_trades_pnl)) * 100
        
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        
        metrics['profit_factor'] = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
        metrics['avg_win'] = (sum(wins) / len(wins)) if wins else 0
        metrics['avg_loss'] = (sum(losses) / len(losses)) if losses else 0

    # Calculate Max Drawdown from P&L History
    if pnl_history_data:
        values = [item['value'] for item in pnl_history_data]
        if values:
            running_max = np.maximum.accumulate(values)
            # Avoid division by zero
            with np.errstate(divide='ignore', invalid='ignore'):
                drawdowns = (running_max - values) / running_max
            # Handle possible NaNs from division by zero if running_max is 0
            drawdowns = np.nan_to_num(drawdowns)
            metrics['max_drawdown'] = np.max(drawdowns) * 100
        
    return metrics

# --- Buy & Hold Calculation ---
def calculate_buy_and_hold(start_time, starting_capital, config):
    """
    Fetches OHLCV to find price of BTC/ETH at start_time vs now.
    """
    # Only try to connect if API keys are present
    if not config.get('api_key') or not config.get('api_secret'):
        return {"BTC/USD": {"pnl": 0, "roi": 0}, "ETH/USD": {"pnl": 0, "roi": 0}}

    exchange = ccxt.coinbase({'apiKey': config['api_key'], 'secret': config['api_secret']})
    benchmarks = ["BTC/USD", "ETH/USD"]
    results = {}
    
    # Convert string timestamp to millisecond integer
    try:
        if isinstance(start_time, str):
            dt_obj = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
            since_ms = int(dt_obj.timestamp() * 1000)
        else:
            # Handle pandas Timestamp or other formats
            since_ms = int(pd.to_datetime(start_time).timestamp() * 1000)
    except:
        since_ms = int(time.time() * 1000) - (24 * 60 * 60 * 1000)

    for symbol in benchmarks:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, '1h', since=since_ms, limit=1)
            current_ticker = exchange.fetch_ticker(symbol)
            
            if ohlcv and current_ticker:
                start_price = ohlcv[0][1] # Open price of first candle
                current_price = current_ticker['last']
                
                # Calculate if we just bought this coin at start
                coin_amount = starting_capital / start_price
                current_value = coin_amount * current_price
                pnl = current_value - starting_capital
                
                results[symbol] = {
                    "pnl": pnl,
                    "roi": ((current_price - start_price) / start_price) * 100
                }
        except Exception as e:
            print(f"Error calc benchmark for {symbol}: {e}")
            results[symbol] = {"pnl": 0.0, "roi": 0.0}
            
    return results

def main_analysis(log_queue, event_queue):
    print("\n--- Starting Portfolio Analysis ---")
    init_database() 
    config = load_config()
    if not config: return {"status": "error", "message": "Failed to load config"}

    analysis_data = {
        "total_pnl": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "total_portfolio_value": 0.0,
        "vault_value": 0.0,
        "metrics": {},
        "buy_and_hold": {},
        "pnl_history": [],
        "recent_trades": []
    }
    
    starting_capital = config.get('starting_capital', 10000.0)

    # 1. Load Trades
    conn = sqlite3.connect('trades.db')
    trades_df = pd.read_sql_query("SELECT * FROM trades", conn)
    
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT 50")
    rows = cursor.fetchall()
    analysis_data['recent_trades'] = [dict(row) for row in rows]
    for t in analysis_data['recent_trades']:
        if not t.get('logic_metadata'): t['logic_metadata'] = "{}"
    conn.close()

    # 2. Basic P&L
    if not trades_df.empty:
        # Simple estimation for realized PnL based on DB columns
        trades_df['cost'] = trades_df.apply(lambda r: r['price'] * r['amount'] if r['action'] == 'BUY' else 0, axis=1)
        trades_df['revenue'] = trades_df.apply(lambda r: r['price'] * r['amount'] if r['action'] == 'SELL' else 0, axis=1)
        analysis_data['realized_pnl'] = trades_df['revenue'].sum() - trades_df['cost'].sum()
        
        # Calculate Buy & Hold Benchmarks using first trade date
        first_trade_time = trades_df['timestamp'].min()
        print(f"Comparing performance since first trade: {first_trade_time}")
        analysis_data['buy_and_hold'] = calculate_buy_and_hold(first_trade_time, starting_capital, config)

    # 3. Portfolio & Vault
    try:
        with open('portfolio.json', 'r') as f: portfolio = json.load(f)
    except: portfolio = {'assets': {}, 'cash': starting_capital}

    cash_balance = portfolio.get('cash', 0)
    
    sweep_asset = config.get('profit_sweeping', {}).get('asset_to_buy', 'USDC/USD')
    
    # Vault Value
    if config.get('live_trading', False) and config.get('api_key'):
        try:
            exchange = ccxt.coinbase({'apiKey': config['api_key'], 'secret': config['api_secret']})
            bal = exchange.fetch_balance()
            analysis_data['vault_value'] = bal.get(sweep_asset.split('/')[0], {}).get('total', 0.0)
        except: pass
    else:
        # Fallback to DB sum for simulation/offline
        if not trades_df.empty and 'action' in trades_df.columns:
            vault_df = trades_df[(trades_df['symbol'] == sweep_asset) & (trades_df['action'] == 'SWEEP')]
            analysis_data['vault_value'] = vault_df['amount'].sum() if not vault_df.empty else 0.0
    
    # 4. Total Portfolio Value Calculation
    total_open_cost = 0
    current_market_val = 0
    
    # We need an exchange instance to check current prices
    exchange = None
    if config.get('api_key'):
        exchange = ccxt.coinbase({'apiKey': config['api_key'], 'secret': config['api_secret']})
    
    for symbol, trades_list in portfolio.get('assets', {}).items():
        if not trades_list: continue
        cost = sum(t['cost_basis'] for t in trades_list)
        amt = sum(t['amount'] for t in trades_list)
        total_open_cost += cost
        
        # Try to get live price, fall back to cost if offline
        try:
            if exchange:
                price = exchange.fetch_ticker(symbol)['last']
                current_market_val += amt * price
            else:
                current_market_val += cost 
        except:
            current_market_val += cost 

    analysis_data['unrealized_pnl'] = current_market_val - total_open_cost
    analysis_data['total_portfolio_value'] = cash_balance + current_market_val + analysis_data['vault_value']
    analysis_data['total_pnl'] = analysis_data['total_portfolio_value'] - starting_capital

    # 5. P&L History Reading
    try:
        # Robust CSV reading that handles potential whitespace
        if os.path.exists('pnl_history.csv'):
            pnl_df = pd.read_csv('pnl_history.csv', skipinitialspace=True)
            pnl_df['timestamp'] = pd.to_datetime(pnl_df['timestamp'])
            analysis_data['pnl_history'] = [
                {"date": r['timestamp'].strftime('%Y-%m-%d %H:%M'), "value": r['portfolio_value']}
                for _, r in pnl_df.iterrows()
            ]
    except Exception as e: 
        print(f"Error reading PnL history: {e}")
    
    if not analysis_data['pnl_history']:
         analysis_data['pnl_history'] = [{"date": datetime.now().strftime('%Y-%m-%d %H:%M'), "value": analysis_data['total_portfolio_value']}]

    # 6. Advanced Metrics
    analysis_data['metrics'] = calculate_advanced_metrics(trades_df, analysis_data['pnl_history'])
    
    event_queue.put(f"📈 Analysis Complete.")
    return analysis_data

if __name__ == "__main__":
    # Simple test execution
    q = queue.Queue()
    res = main_analysis(q, q)
    print(json.dumps(res, indent=2, default=str))
import sys
import io
import json
import threading
import queue
from flask import Flask, render_template, request, jsonify, send_from_directory, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
from colorama import init
import os
import re
import logging
from logging.handlers import RotatingFileHandler
import shutil
import admin_utils
from dotenv import load_dotenv
import socket

# --- Import your other scripts as modules ---
import trading_bot
import analysis
import audit 

# --- Helper Function: ANSI to HTML Conversion ---
def ansi_to_html(text):
    """Converts terminal ANSI color codes into web-safe HTML spans."""
    if not isinstance(text, str):
        return text
        
    # 1. Convert 24-bit RGB ANSI codes, accounting for optional bold/style prefixes (e.g. \033[1;38;2;...)
    text = re.sub(r'\x1b\[(?:[0-9]+;)?38;2;(\d+);(\d+);(\d+)m', r'<span style="color: rgb(\1,\2,\3);">', text)
    
    # 2. Convert standard 16-color ANSI codes (Red, Green, Yellow, Blue, etc.)
    color_map = {
        '31': '#e74c3c', # Red
        '32': '#2ecc71', # Green
        '33': '#f1c40f', # Yellow
        '34': '#3498db', # Blue
        '35': '#9b59b6', # Magenta
        '36': '#00cec9', # Cyan
    }
    def map_standard(match):
        code = match.group(1)
        return f'<span style="color: {color_map.get(code, "white")};">'
        
    text = re.sub(r'\x1b\[(?:[0-9]+;)?(3[1-6])m', map_standard, text)
    
    # 3. Handle resets to close the spans
    text = re.sub(r'\x1b\[0?m', r'</span>', text)
    
    # 4. Strip any remaining unsupported ANSI codes to keep the text clean
    ansi_escape = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
    clean_text = ansi_escape.sub('', text)
    
    return clean_text.strip()

# --- Helper Function: Final JSON Sanitization ---
def clean_ansi(text):
    """Strips all ANSI escape codes and rogue control characters from a string."""
    if not isinstance(text, str):
        return text
    
    # 1. Strip ANSI escape codes
    ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]')
    clean_text = ansi_escape.sub('', text)

    # 2. Aggressive ASCII filtering
    cleaned_ascii = ''.join(char for char in clean_text if 32 <= ord(char) <= 126 or char in ('\n', '\t', ' ', ':', '.', '$', '%', '/', '(', ')', '[', ']', '<', '>', '+', '=', '-', '|'))

    return cleaned_ascii.strip()

# --- Setup Flask App ---
app = Flask(__name__)

# Static Session Security (Driven by .env)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "fallback_local_secret_key_123")

# Single Admin Authentication (Driven by .env)
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS_HASH = generate_password_hash(os.getenv("ADMIN_PASSWORD", "password123"))

app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0 # Disable caching

# --- Bot Management & Queues (Shared Memory) ---
bot_thread = None
bot_status = {} 
log_queue = queue.Queue() 
event_queue = queue.Queue() 

def start_bot_in_background():
    """Wrapper to run the bot and handle its completion."""
    try:
        # Pass the shared status and queues to the bot's logic
        trading_bot.start_bot_logic(bot_status, log_queue, event_queue)
    except Exception as e:
        # We must use the original stdout here
        original_stdout.write(f"--- FATAL ERROR IN BOT THREAD: {e} ---\n")
        original_stdout.flush()
    original_stdout.write("--- Bot thread has stopped ---\n")
    original_stdout.flush()

# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        # Single Admin Authentication
        if username == ADMIN_USER and check_password_hash(ADMIN_PASS_HASH, password):
            session['logged_in'] = True
            session['username'] = username
            session['role'] = 'admin'
            return redirect(url_for('index'))
        else:
            error = 'Invalid Credentials'

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
def index():
    # --- SECURITY CHECK ---
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    return render_template('index.html', user_role='admin')

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/changelog')
def changelog_page():
    return render_template('changelog.html')

@app.route('/portfolio')
def portfolio_page():
    return render_template('portfolio.html')

@app.route('/start', methods=['POST'])
def start_bot():
    global bot_thread
    if bot_thread and bot_thread.is_alive():
        return jsonify({"status": "error", "message": "Bot is already running."}), 400
    
    # --- V3 SAFETY INTERLOCK ---
    # If the user is a Guest, we FORCE 'live_trading' to False in the shared status
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized: Admin Access Required'}), 403
    # ----------------------
        
        # OPTIONAL: You can inject a flag here if your bot logic supports it
        # trading_bot.force_paper_mode = True 
        
    # ---------------------------

    trading_bot.stop_requested = False
    bot_thread = threading.Thread(target=start_bot_in_background, daemon=True)
    bot_thread.start()
    event_queue.put({"message": "Bot started successfully.", "type": "success"})
    return jsonify({"status": "success", "message": "Bot started."})

@app.route('/stop', methods=['POST'])
def stop_bot():
    global bot_thread
    if not bot_thread or not bot_thread.is_alive():
        return jsonify({"status": "error", "message": "Bot is not running."}), 400
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized: Admin Access Required'}), 403
    # ----------------------    

    trading_bot.stop_requested = True
    event_queue.put({"message": "Stop signal sent. Bot will not trade until started.", "type": "error"})
    return jsonify({"status": "success", "message": "Stop signal sent."})

@app.route('/api/reset_bot', methods=['POST'])
def reset_bot_route():
    # --- SECURITY CHECK ---
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': 'Unauthorized: Admin Access Required'}), 403
    # ----------------------
    try:
        data = request.get_json()
        mode = data.get('mode', 'soft')
        
        if mode == 'soft':
            success = admin_utils.soft_reset(starting_capital=10000.0)
            if success:
                return jsonify({"status": "success", "message": "Soft Reset Complete. Balance reset to $10,000."})
            else:
                return jsonify({"status": "error", "message": "Soft Reset Failed"}), 500
                
        elif mode == 'hard':
            success = admin_utils.hard_reset()
            if success:
                return jsonify({"status": "success", "message": "Hard Reset Complete."})
            else:
                return jsonify({"status": "error", "message": "Hard Reset Failed"}), 500
        
        else:
            return jsonify({"status": "error", "message": f"Unknown reset mode: {mode}"}), 400

    except Exception as e:
        print(f"ERROR in /api/reset_bot: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/logs')
def get_logs():
    logs = []
    while not log_queue.empty():
        logs.append(ansi_to_html(log_queue.get_nowait()))
    return jsonify({"logs": logs})

@app.route('/events')
def get_events():
    events = []
    while not event_queue.empty():
        item = event_queue.get_nowait()
        if isinstance(item, dict):
            item['message'] = clean_ansi(item['message'])
            events.append(item)
        else:
            events.append({
                "message": clean_ansi(item),
                "type": "info"
            })
    return jsonify({"events": events})

@app.route('/config', methods=['GET'])
def get_config():
    try:
        with open('config.json', 'r') as f: config_data = json.load(f)
        return jsonify(config_data)
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/config', methods=['POST'])
def save_config():
    # --- SECURITY CHECK ---
    if session.get('role') != 'admin':
        return jsonify({"status": "error", "message": "⛔ Access Denied: Admin privileges required to edit Config."}), 403
    # ----------------------
    
    try:
        config_string = request.data.decode('utf-8')
        new_config = json.loads(config_string)
        with open('config.json', 'w') as f: json.dump(new_config, f, indent=2)
        
        event_queue.put({
            "message": "Config Saved - Using new settings on next cycle", 
            "type": "config"
        })
        
        return jsonify({"status": "success", "message": "Config saved."})
    except json.JSONDecodeError:
        return jsonify({"status": "error", "message": "Error: Invalid JSON format."}), 400
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500
        
@app.route('/status')
def get_status():
    global bot_thread 
    is_running = bool(bot_thread and bot_thread.is_alive())
    status_data = bot_status.get("global", {}).copy()
    symbols_data = bot_status.get("symbols", {}).copy()
    status_data['is_running'] = is_running
    
    for key, value in status_data.items():
        status_data[key] = clean_ansi(value)
        
    for symbol, info in symbols_data.items():
        for key, value in info.items():
            if isinstance(value, str):
                info[key] = clean_ansi(value)

    return jsonify({
        "global": status_data,
        "symbols": symbols_data
    })

@app.route('/analysis_data')
def get_analysis_data():
    try:
        data_queue = queue.Queue()
        def analysis_thread_wrapper():
            original_stdout_temp = sys.stdout
            sys.stdout = io.StringIO()
            
            data = analysis.main_analysis(log_queue, event_queue)
            data_queue.put(data)
            
            sys.stdout = original_stdout_temp
            
        thread = threading.Thread(target=analysis_thread_wrapper, daemon=True)
        thread.start()
        data = data_queue.get(timeout=30) 
        return jsonify(data)
        
    except queue.Empty:
        return jsonify({"status": "error", "message": "Analysis timed out"}), 500
    except Exception as e:
        original_stdout.write(f"Error running on-demand analysis: {e}\n")
        original_stdout.flush()

@app.route('/pnl_history.csv')
def get_pnl_csv():
    return send_from_directory('.', 'pnl_history.csv')

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/api/run_audit', methods=['GET'])
def run_audit_route():
    try:
        report_html = audit.fetch_audit_report(is_web=True)
        return jsonify({"status": "success", "report": report_html})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500    

@app.route('/api/set_profile', methods=['POST'])
def set_profile():
    data = request.json
    profile_name = data.get('profile')
    filename = f"config_{profile_name}.json"
    if not os.path.exists(filename):
        return jsonify({"status": "error", "message": f"Profile {filename} not found."}), 404
    try:
        shutil.copy(filename, 'config.json')
        return jsonify({"status": "success", "message": f"Loaded {profile_name.upper()} profile."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/liquidate/<path:symbol>', methods=['POST'])
def api_liquidate(symbol):
    # Decode symbol (e.g., "BTC-USD" -> "BTC/USD")
    clean_symbol = symbol.replace('-', '/')
    
    # Call the bot logic
    # (Adjust 'bot' to whatever your instance variable is named)
    result = trading_bot.force_sell_position(clean_symbol) 
    
    return jsonify(result)     

# --- V3.2: MANUAL LIQUIDATION ENDPOINT ---
import urllib.parse

def force_sell_position(self, symbol):
        """ Manually sells 100% of a position immediately. """
        try:
            # 1. Check if we hold it
            if symbol not in self.portfolio.get('assets', {}):
                return {"status": "error", "message": "Symbol not held in portfolio."}

            trades = self.portfolio['assets'][symbol]
            total_amount = sum(t['amount'] for t in trades)
            
            if total_amount <= 0:
                return {"status": "error", "message": "Holding amount is 0."}

            # 2. Execute Market Sell
            # (Assuming self.exchange is your ccxt instance)
            order = self.exchange.create_market_sell_order(symbol, total_amount)
            
            # 3. Update Portfolio (Remove asset)
            del self.portfolio['assets'][symbol]
            self.save_portfolio() # Ensure this method exists or use your save logic
            
            # 4. Log it
            self.log_event(f"MANUAL LIQUIDATION: Sold {total_amount} {symbol}", "sell")
            
            return {"status": "success", "message": f"Sold {total_amount} {symbol}"}

        except Exception as e:
            logging.error(f"Force Sell Failed: {e}")
            return {"status": "error", "message": str(e)}
              

def get_local_ip():
    """Reliably fetches the local LAN IP address across Windows, Mac, and Linux."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Doesn't actually send a packet, just initializes the routing table
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == '__main__':
    # 1. Initialize colorama
    init(autoreset=True) 

    # 2. Force streams to be clean UTF-8
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

    # 3. Save original terminal streams
    global original_stdout
    global original_stderr
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    # 4. Logging & Silence Werkzeug (Flask Logs)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    rotation_handler = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    rotation_handler.setFormatter(formatter)
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(rotation_handler)
    
    # Silence the default Flask startup spam
    logging.getLogger('werkzeug').disabled = True

    # --- LAN BIND (For Remote/Headless Access) ---
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        local_ip = get_local_ip()
        print(f"--- 🚀 STARTING CRYPTOPI LOCAL SERVER ---")
        print(f"    -> Dashboard available on your local network.") 
        print(f"    -> Access it via your browser: http://{local_ip}:5000")
    
    app.run(host='0.0.0.0', port=5000, debug=True)
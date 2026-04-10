import json
import sqlite3
import os
import sys
import shutil
import glob
from datetime import datetime

# --- CONFIGURATION ---
PORTFOLIO_FILE = 'portfolio.json'
DB_FILE = 'trades.db'
PNL_FILE = 'pnl_history.csv'

# The file the bot READS
ACTIVE_CONFIG = 'config.json' 
# The file used to RESTORE defaults
DEFAULT_CONFIG = 'config-default.json' 

# Archive Settings
ARCHIVE_ROOT = "archives"
FILES_TO_BACKUP = [
    "portfolio.json",
    "trades.db",
    "pnl_history.csv",
    "config.json",
    "bot.log",       
    "app.log",       
    "config_*.json"  # Wildcard for all profile configs
]

def create_archive(tag="manual"):
    """
    Creates a timestamped snapshot of the bot's current state.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    archive_name = f"archive_{timestamp}_{tag}"
    dest_dir = os.path.join(ARCHIVE_ROOT, archive_name)

    print(f"📦 Creating Backup Snapshot: {dest_dir} ...")

    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        print(f"❌ Error creating backup directory: {e}")
        return False

    files_found = 0
    for pattern in FILES_TO_BACKUP:
        matches = glob.glob(pattern)
        if not matches:
            continue

        for filename in matches:
            try:
                if os.path.exists(filename):
                    shutil.copy2(filename, dest_dir)
                    print(f"   -> Archived: {filename}")
                    files_found += 1
            except Exception as e:
                print(f"   ❌ Failed to copy {filename}: {e}")

    if files_found > 0:
        print(f"✅ Archive complete ({files_found} files).")
        return True
    else:
        print("⚠️  Warning: No files were found to archive.")
        return True # Return true anyway so reset can proceed

def soft_reset(starting_capital=10000.0):
    """
    Resets the money and trade history, but KEEPS your strategy/config.
    """
    print(f"--- INITIATING SOFT RESET (Capital: ${starting_capital}) ---")
    
    # 0. SAFETY ARCHIVE
    create_archive(tag="pre_soft_reset")

    # 1. Reset Portfolio
    try:
        new_portfolio = {
            "cash": starting_capital,
            "assets": {},
            "last_sell_prices": {}
        }
        with open(PORTFOLIO_FILE, 'w') as f:
            json.dump(new_portfolio, f, indent=4)
        print(f"✅ Portfolio reset to ${starting_capital}")
    except Exception as e:
        print(f"❌ Failed to reset portfolio: {e}")

    # 2. Clear Database
    try:
        if os.path.exists(DB_FILE):
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM trades") 
            conn.commit()
            conn.close()
            print("✅ Trade Database cleared.")
    except Exception as e:
        print(f"❌ Failed to clear database: {e}")

    # 3. Clear P&L History
    try:
        if os.path.exists(PNL_FILE):
            os.remove(PNL_FILE)
            print("✅ P&L History deleted.")
    except Exception as e:
        print(f"❌ Failed to delete P&L history: {e}")
        
    print("--- SOFT RESET COMPLETE ---")
    return True

def hard_reset():
    """
    WARNING: Resets EVERYTHING.
    Restores config.json from config-default.json.
    """
    print("--- INITIATING HARD RESET ---")
    
    # 0. SAFETY ARCHIVE (Done inside soft_reset, but let's tag specifically for Hard)
    create_archive(tag="pre_hard_reset")

    # 1. Run Soft Reset logic manually (skipping the archive call inside it to avoid duplicates)
    # Actually, calling soft_reset() is cleaner, it will just make a second backup which is safer.
    soft_reset() 
    
    # 2. Restore Default Config
    print("⚠ Overwriting config.json with factory defaults...")
    try:
        if os.path.exists(DEFAULT_CONFIG):
            shutil.copy(DEFAULT_CONFIG, ACTIVE_CONFIG)
            print(f"✅ Restored {ACTIVE_CONFIG} from {DEFAULT_CONFIG}")
        else:
            print(f"❌ Error: {DEFAULT_CONFIG} not found. Cannot restore defaults.")
    except Exception as e:
        print(f"❌ Failed to restore config: {e}")
    
    return True

if __name__ == "__main__":
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode == 'soft':
            soft_reset()
        elif mode == 'hard':
            hard_reset()
        elif mode == 'archive':
            create_archive(tag="manual_cli")
        else:
            print("Usage: python admin_utils.py [soft|hard|archive]")
    else:
        print("Usage: python admin_utils.py [soft|hard|archive]")
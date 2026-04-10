from .base_strategy import BaseStrategy

class AccumulatorStrategy(BaseStrategy):
    """
    The 'Event Horizon' Strategy.
    Philosophy: Sniper Entry, Human Exit.
    - No Auto-Selling (Diamond Hands).
    - Stricter Buy Conditions (Deep Dips only).
    - Fixed 'Bullet' sizing (Rations ammo).
    """

    def decide_action(self, config, symbol, analysis_data, current_position):
        # Unpack Data
        rsi = analysis_data.get('rsi', 50)
        current_price = analysis_data.get('current_price', 0)
        cash = analysis_data.get('cash', 0)
        score = 0  # We don't really use score for accumulation, just binary triggers
        
        # Load Special Configs (with defaults)
        acc_config = config.get('event_horizon_config', {})
        strict_rsi = acc_config.get('strict_rsi_threshold', 25)
        buy_amount = acc_config.get('accumulator_buy_amount_usd', 250.0)
        reserve_pct = acc_config.get('min_cash_reserve_pct', 0.1) # Keep 10% dry powder
        emergency_stop = acc_config.get('emergency_stop_pct', -50.0)

        # --- A. HOLD / SELL LOGIC (Diamond Hands) ---
        if current_position:
            # 1. Emergency Stop Loss (The only time we sell)
            pnl_pct = analysis_data.get('pnl', 0)
            if pnl_pct < emergency_stop:
                return "SELL", f"Emergency Stop Triggered ({pnl_pct:.1f}%)", -999
            
            # 2. Never Auto-Sell otherwise
            return "HOLD", "Accumulating (Manual Exit Only)", 999

        # --- B. BUY LOGIC (Sniper) ---
        
        # 1. Check Cash Reserves (Ammo Rationing)
        start_cap = config.get('starting_capital', 10000)
        min_reserve = start_cap * reserve_pct
        if cash < min_reserve:
            return "BLOCKED", f"Cash Reserve Low (< ${min_reserve:.0f})", 0
        
        if cash < buy_amount:
            return "BLOCKED", "Insufficient Cash for Bullet", 0

        # 2. Strict RSI Check
        if rsi > strict_thresh:
            return "BLOCKED", f"RSI too high ({rsi:.1f} > {strict_rsi})", 0

        # 3. Volume Check (Still want liquid assets)
        if not analysis_data.get('vol_passed', True):
            return "BLOCKED", "Low Volume", 0

        # 4. MA Filter? 
        # For accumulation, we often WANT to buy below the MA (the dip). 
        # So we explicitly IGNORE the MA Filter here.
        
        return "BUY", "Sniper Entry Triggered", 999
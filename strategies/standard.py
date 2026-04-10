from .base_strategy import BaseStrategy

class StandardStrategy(BaseStrategy):
    """
    Refactored Logic from TradingBot v2.4/3.0
    Decides based on Score, RSI, Market Regime, AND ATR Stops.
    """
    def decide_action(self, config, symbol, analysis_data, current_position):
        # Unpack Analysis Data
        score = analysis_data.get('score', 0)
        rsi = analysis_data.get('rsi', 50)
        market_character = analysis_data.get('market_character', 'Ranging')
        global_regime = analysis_data.get('global_regime', 'neutral')
        local_regime = analysis_data.get('local_regime', 'neutral')
        local_slope = analysis_data.get('local_slope', 0)
        vol_passed = analysis_data.get('vol_passed', True)
        current_price = analysis_data.get('current_price', 0)
        
        # Unpack Thresholds
        buy_threshold = analysis_data.get('buy_thresh', 1.5)
        sell_threshold = analysis_data.get('sell_thresh', -1.5)
        
        # Determine basic condition matches
        buy_cond = (market_character == "Trending" and score >= buy_threshold) or \
                   (market_character == "Ranging" and (global_regime in ['bull', 'neutral']) and score <= sell_threshold)

        sell_cond = (market_character == "Trending" and score <= sell_threshold) or \
                    (market_character == "Ranging" and (global_regime in ['bear', 'neutral']) and score >= buy_threshold)

        # --- A. BUY LOGIC ---
        if buy_cond and not current_position:
            # 1. Bear Safety Lock
            use_safety = config.get('bear_trend_safety_lock', True)
            is_bear_crash = (local_regime == 'bear') and (local_slope == -1) and (market_character == 'Trending')
            prev_rsi = analysis_data.get('prev_rsi', 50)
            
            # 2. Oversold Override
            is_oversold = rsi < config.get('rsi_oversold_override', 25)

            if is_oversold:
                if not vol_passed: return "BLOCKED", "Oversold but Low Vol", score
                return "BUY", "Oversold Override", score
            
            if use_safety and is_bear_crash:
                # Check for bounce
                bounce_thresh = config.get('bear_bounce_rsi_threshold', 25)
                if rsi < bounce_thresh and rsi > prev_rsi:
                    return "BUY", "Bear Bounce (Safety Override)", 999
                return "BLOCKED", "Bear Trend Safety Lock", score

            if global_regime == 'bear':
                return "BLOCKED", "Global Bear Market", score

            if rsi > config.get('rsi_config', {}).get('overbought', 70):
                return "BLOCKED", "RSI Overbought", score

            if not vol_passed and score < (buy_threshold + 0.5):
                return "BLOCKED", "Low Volume", score

            # MA Filter Check
            if not analysis_data.get('ma_passed', True):
                 return "BLOCKED", "MA Filter", score

            return "BUY", "Standard Signal", score

        # --- B. SELL LOGIC (Now Includes ATR Stops) ---
        elif current_position:
            # 0. Accumulator Mode (HODL)
            # If enabled, we ignore all Sell/Stop logic below.
            if config.get('accumulator_mode', False):
                return "HOLD", "Accumulator Mode", score
            # 1. ATR Trailing Stop Loss
            # We use the HWM (High Water Mark) passed from the bot
            hwm = analysis_data.get('high_water_mark', 0)
            atr_value = analysis_data.get('atr_value', 0)
            
            if hwm > 0 and atr_value > 0:
                atr_config = config.get('atr_stop_loss_config', {})
                multiplier = atr_config.get('multiplier', 3.0)
                stop_price = hwm - (atr_value * multiplier)
                
                if current_price < stop_price:
                    return "SELL", f"ATR Stop Loss Triggered ({current_price} < {stop_price:.2f})", score

            # 2. Take Profit
            tp_percent = config.get('take_profit_percent', 0.05) # 5% default
            avg_entry = analysis_data.get('avg_entry_price', 0)
            if avg_entry > 0:
                take_profit_price = avg_entry * (1 + tp_percent)
                if current_price >= take_profit_price:
                    return "SELL", f"Take Profit Hit ({current_price} > {take_profit_price:.2f})", score

            # 3. Standard Sell Signals
            if sell_cond:
                # Dip Immunity (Don't sell dips on weak signals)
                if any(t.get('trade_type') == 'dip' for t in current_position):
                    return "HOLD", "Dip Position Immunity", score

                if rsi < config.get('rsi_config', {}).get('oversold', 30):
                    return "BLOCKED", "RSI Oversold (Wait for bounce)", score
                
                if not vol_passed:
                    if market_character == "Ranging":
                        return "SELL", "Ranging Sell (Low Vol Allowed)", score
                    return "BLOCKED", "Low Volume Sell", score

                return "SELL", "Standard Signal", score

        # --- C. DIP BUY LOGIC ---
        elif not current_position and analysis_data.get('last_sell_price'):
            last_price = analysis_data['last_sell_price']
            dip_target = analysis_data.get('dip_target', 0)
            
            if dip_target > 0 and current_price <= dip_target:
                 # Safety Checks
                 use_safety = config.get('bear_trend_safety_lock', True)
                 is_bear_crash = (local_regime == 'bear') and (local_slope == -1) and (market_character == 'Trending')
                 
                 if use_safety and is_bear_crash:
                     return "BLOCKED", "Dip Blocked (Bear Trend)", score
                 
                 if not analysis_data.get('ma_passed', True):
                     return "BLOCKED", "Dip Blocked (MA Broken)", score

                 return "DIP_BUY", "ATR Dip Target Hit", 999

        return "IDLE", "No Signal", score
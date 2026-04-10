# CryptoPi: Autonomous Market-Regime Trading Engine

CryptoPi is a modular, quantitative trading engine designed to automate cryptocurrency accumulation and profit-taking using **edge computing**. Originally developed for Raspberry Pi, this open-source fork is optimized for high-performance execution in any local Windows, Linux, or WSL environment.

This is not a "set and forget money printer." I learned the hard way that algorithmic trading amplifies your own technical analysis rather than replacing it. The bot performs well when the market trends upward, but takes a lot of babysitting and strategy-tweaking when the market goes down. Treat it as a tool, not an oracle.

> **🔴 Live Demo:** See CryptoPi running in real-time at [cryptopi.live](https://cryptopi.live)
>
> Guest PIN: `2214` (read-only - no bot control)

### **Why I Open Sourced This Project**

I decided to make CryptoPi public for three main reasons:
1. **Giving Back:** I have always deeply appreciated the open-source developers who share their tools and knowledge, and I wanted to finally put something of my own out into the community.

2. **Passing the Baton:** I have pushed this engine to my current technical limit. While the foundation is highly robust, there is plenty of room for expansion. Like building an automatic strategy profile switcher based on live market indicators (hint, hint, to any one looking to contribute).

3. **New Horizons:** I have some other projects I am incredibly excited to spend my free time on. By open-sourcing this, the bot can continue to evolve and improve through community pull requests while I step back from active feature development.

4. **Testing the AI Waters:** I wanted to test the capabilities of AI as a co-pilot to aid in development, and use it as a tool to learn more about UX design in JavaScript and network architecture in Python.
---

### **The Quant Strategy: Market-Regime Switching**

CryptoPi utilizes a **Dynamic Regime-Switching** architecture. The engine analyzes market "texture" to determine which strategy to employ in real-time.

* **Trending Bull Mode:** Activated when the Average Directional Index (ADX) signals strong momentum. The bot employs MACD and RSI crossovers to maximize gains during sustained upward moves.
* **Ranging / Accumulator Mode:** Activated during low-volatility or "sideways" markets. The bot switches to a DCA (Dollar Cost Averaging) strategy, using ATR-based volatility filters to set precise entry points, effectively "stocking the shelves" for the next breakout.

For a full breakdown of the strategy logic, indicator weights, and scoring system, see the **Help** page inside the dashboard after installation.

---

### **Technical Architecture**

The project is structured into three distinct layers to maintain a clean separation between financial execution and user interaction.

| Component | Layer | Description |
| :--- | :--- | :--- |
| **`trading_bot.py`** | **The Brain** | The core engine. Handles technical analysis, exchange heartbeats, and order execution as a persistent background process. |
| **`app.py`** | **The Backend/UX** | A Flask-based server that bridges the gap. Manages secure sessions, reads the bot's live state, and provides a RESTful API for the frontend. |
| **`index.html`** | **The Interface** | A responsive dashboard providing real-time visualization of PnL, active trades, and current market regime status. |

---

## Prerequisites

* **Python 3.9+** - [Download](https://www.python.org/downloads/)
* **Coinbase Advanced Trade API Keys** - [Generate here](https://www.coinbase.com/settings/api)
* **Git** (optional, for cloning)

---

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/Lecheric/cryptopi.git
cd cryptopi
```

### 2. Run the Setup Script

**Windows:**
```
setup.bat
```

**Linux / WSL / Mac:**
```bash
chmod +x setup.sh
./setup.sh
```

The setup script will automatically:
- Create a Python virtual environment (`.venv`)
- Install all dependencies from `requirements.txt`
- Prompt you to set an **Admin username and password** for the dashboard
- Generate your `.env` and `config.json` from the provided templates
- Walk you through adding your **Coinbase API keys**

### 3. Add Your Coinbase API Keys

During setup you will be prompted to place your `coinbase_keys.json` file in the project root. This file is downloaded directly from Coinbase when you create an API key.

The file should look like this:

```json
{
  "name": "organizations/xxxxx/apiKeys/xxxxx",
  "privateKey": "-----BEGIN EC PRIVATE KEY-----\nYOUR_KEY_HERE\n-----END EC PRIVATE KEY-----\n"
}
```

> **⚠️ For initial testing, create a key with READ-ONLY permissions.** Do not enable Trade or Withdraw permissions until you are ready to risk real capital.

**"Why does this bot need my API keys?"**: This is a fair and healthy question. The bot requires authenticated Coinbase API access to fetch real-time market data (prices, candles, volume) and to execute trades when Live Mode is enabled. Your keys are stored locally in `coinbase_keys.json` and `.env` both are git-ignored and never leave your machine. They are never transmitted to any external server, cloud service, or third party. The entire codebase is open source specifically so you can verify this yourself. If you don't trust it, read `trading_bot.py` and `app.py` before adding your keys.

### 4. Start the Bot

**Windows:**
```
start.bat
```

**Linux / WSL / Mac:**
```bash
./start.sh
```

For a full breakdown of the strategy logic, indicator weights, and scoring system, see the **Help** page inside the dashboard after installation.

---

## File Reference

```
cryptopi/
├── app.py                    # Flask server & dashboard backend
├── trading_bot.py            # Core trading engine
├── config.json               # Active bot configuration (generated)
├── config.example.json       # Template configuration
├── config_default.json       # Strategy profile: Standard
├── config_safe.json          # Strategy profile: Safe (Scalper)
├── config_scarcity.json      # Strategy profile: Scarcity (Trend)
├── config_volatile.json      # Strategy profile: Volatile (Degen)
├── config_sniper.json        # Strategy profile: Sniper
├── config_turbo.json         # Strategy profile: Turbo
├── config_tester.json        # Strategy profile: Tester
├── coinbase_keys.json        # Your API keys (generated, git-ignored)
├── coinbase_keys.example.json# Template for API keys
├── .env                      # Dashboard credentials (generated, git-ignored)
├── .env.example              # Template for environment variables
├── portfolio.json            # Live portfolio state (git-ignored)
├── trades.db                 # SQLite trade history (git-ignored)
├── setup.bat                 # Windows setup script
├── setup.sh                  # Linux/Mac setup script
├── start.bat                 # Windows start script
├── start.sh                  # Linux/Mac start script
├── requirements.txt          # Python dependencies
├── LICENSE                   # MIT License
├── templates/                # HTML templates
│   ├── index.html            # Main dashboard
│   ├── login.html            # Authentication page
│   ├── portfolio.html        # Portfolio & PnL view
│   ├── help.html             # Strategy documentation
│   └── changelog.html        # Version history
├── static/                   # CSS, favicon, assets
│   └── style.css
└── strategies/               # Modular strategy engines
    ├── standard.py
    └── accumulator.py
```

---

## Security Model

1. **Local-Only Binding:** The dashboard binds to `127.0.0.1`, making it invisible to the public internet.
2. **The `.env` Protocol:** API keys and credentials live in `.env` and `coinbase_keys.json`, both excluded from Git via `.gitignore`.
3. **Permission Scoping:** Users are instructed to generate API keys with "Trade" permissions only. With "Withdrawal" disabled at the exchange level, the software cannot move funds off-exchange.
4. **Session Security:** The Flask `SECRET_KEY` is pulled from `.env` - not randomized at runtime - so sessions survive reboots.

---

## Ghost Mode (Paper Trading)

By default, CryptoPi runs in **Ghost Mode** - all trades are simulated against a $10,000 paper balance. No real orders are placed.

The "Enable Live Trading" toggle exists in the dashboard UI but **does nothing**. Live trading is force-disabled in the source code as a safety measure. The bot ran for several months in Ghost Mode for stability testing, but Live Mode was never extensively tested against real capital.

If you want to enable live trading, you'll need to find the override in the source code and remove it yourself. **You do this entirely at your own risk.** The developers assume no liability for any trades executed in Live Mode.

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Disclaimer

This software is provided strictly for **educational, evaluation, and simulation purposes**. Nothing in this repository constitutes financial advice, investment guidance, or a recommendation to buy or sell any asset.

Cryptocurrency trading involves **substantial risk of loss**, including the possibility of losing your entire investment. Markets are volatile, unpredictable, and operate 24/7. Automated trading software introduces additional risks including but not limited to: software bugs, API failures, exchange outages, network interruptions, incorrect order execution, stale data, and unexpected behavior during extreme market conditions.

This software is provided **AS IS** without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and noninfringement. The authors and contributors make **no guarantees** about the accuracy, reliability, completeness, or timeliness of the software or any trading signals it generates.

**By downloading, installing, or running this software, you acknowledge and agree that:**

- You are solely responsible for your own capital and trading decisions.
- The creators, contributors, and maintainers assume **no liability** for financial losses, missed opportunities, damages, or unintended trades resulting from the use or misuse of this software.
- Past performance in Ghost Mode (paper trading) is not indicative of future results and does not guarantee profitability with real capital.
- You have read and understood the source code, or accept the risk of running code you have not fully reviewed.
- You will not hold any contributor liable for losses resulting from bugs, market volatility, API changes, exchange policy changes, or any other cause.

**If you are not comfortable with these terms, do not use this software.**
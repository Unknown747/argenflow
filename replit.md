# ArgenFlow V5 Pro

An algorithmic trading bot dashboard for Exness + MetaTrader 5 micro-accounts. Runs mean-reversion and trend-following strategies using RSI, EMA, and ATR indicators with an AI Manager for news filtering and market condition analysis.

## Tech Stack

- **Backend**: Python 3.12 with FastAPI + uvicorn
- **Frontend**: Static HTML dashboard served by FastAPI (`static/index.html`)
- **Trading**: MetaTrader5 library (Windows-only; gracefully unavailable on Linux/Replit)
- **Dependencies**: fastapi, uvicorn[standard], python-dotenv, MetaTrader5

## Project Structure

```
main.py          - FastAPI app, startup loop, API endpoints
bot_engine.py    - ArgenBotPro class: indicators, signals, order execution
ai_manager.py    - AIManager: news calendar filter, market condition classifier
static/index.html - Dashboard UI (dark theme, real-time polling)
requirements.txt - Python dependencies
test_conexion.py - MT5 connection test utility
operaciones.csv  - Auto-generated trade log (CSV)
```

## Running Locally

The app runs on port 5000 with host `0.0.0.0`:

```bash
python main.py
```

Dashboard available at: http://localhost:5000

## Environment Variables

Create a `.env` file with:

```
MT5_LOGIN=your_account_number
MT5_PASS=your_password
MT5_SERVER=Exness-MT5Real  # or Exness-MT5Demo
MT5_DEMO=true              # set to false for real account
```

## Notes

- MetaTrader5 requires a Windows environment with the MT5 terminal installed. On Linux (Replit), the dashboard still loads but trading functions are unavailable.
- The AI Manager uses a news calendar in `berita.json` — update it weekly with high-impact events from Forex Factory.
- Trades are logged to `operasi.csv` automatically.
- Session filter: London/NY hours (07:00–22:00 UTC = 14:00–05:00 WIB), weekdays only.
- Friday is fully blocked (spread melebar jelang weekend).
- Active pairs: EURUSD and GBPUSD only.

## Small Capital Mode ($5–$10)

Activates automatically when balance < $15:
- Risk: 0.5% per trade
- Max lot: 0.01 (micro lot)
- Max open positions: 1
- SL clamped: 15–30 pips, TP = 2× SL

## Safety Features

- Pause 1 hour if account drops >5% in any 1-hour window
- Daily loss limit: 10% (configurable via MAKSIMAL_RUGI_HARIAN_PERSEN)
- Spread filter: max 20 points (2 pips)
- News blackout: 30 min before / 15 min after high-impact events

## Scan Interval

Set to 3 seconds (scalping mode). Configure via `SCAN_INTERVAL_DETIK` in `bot_engine.py`.

## New API Endpoints

- `GET /api/modal_kecil/status` — returns lot, SL, TP, spread per symbol, drawdown remaining, pause status

## Keep-Alive (Replit 24/7)

Run in a separate terminal to prevent Replit from sleeping:
```bash
python keep_alive.py
```

Or import at the top of `main.py`:
```python
import keep_alive
keep_alive.mulai()
```

## Running on Replit (Step by Step)

1. Set environment variables in Replit Secrets:
   - `MT5_LOGIN`, `MT5_PASS`, `MT5_SERVER`, `MT5_DEMO`
2. Install dependencies (done automatically):
   ```bash
   pip install -r requirements.txt
   ```
3. Click **Run** to start the server (port 5000)
4. Open the dashboard in the Preview pane
5. Click **JALANKAN BOT** to start trading
6. (Optional) Open a second terminal and run: `python keep_alive.py`

## Deployment

Configured for autoscale deployment using gunicorn.

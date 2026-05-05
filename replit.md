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
- The AI Manager uses a hardcoded news calendar in `ai_manager.py` — update `NOTICIAS_ALTO_IMPACTO` weekly with high-impact events from Forex Factory.
- Trades are logged to `operaciones.csv` automatically.
- Session filter: London/NY hours only (08:00–17:00 UTC, weekdays).

## Deployment

Configured for autoscale deployment using gunicorn.

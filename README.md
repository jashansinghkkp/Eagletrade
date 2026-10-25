# Insta Trade - Next-Gen Indian Market Trading Terminal

A ultra-fast, premium-grade Web & Mobile Trading Terminal for Indian Markets (NSE & BSE) featuring real-time tick-by-tick market data, live option chains with Greeks, Index Futures, stock search, and multi-user paper trading.

---

## Key Features

- **Multi-User Paper Trading Engine**:
  - Isolated user accounts with secure password hashing and SQLite persistence (`data/trading_terminal.db`).
  - Rs. 10,00,000 (10 Lakhs) virtual trading capital per user.
  - Zero broker API key exposure required — safe for public and shared demo deployments.
- **Real-Time Live Indian Market Data**:
  - Sub-second streaming market ticks for Spot Indices, Index Futures, and 60+ top NSE/BSE equities.
  - Candlestick charts powered by TradingView Lightweight Charts (1m, 5m, 15m, 1h, 1D).
- **Live Option Chain & Greeks**:
  - Full support for NIFTY, BANK NIFTY, SENSEX, FINNIFTY, and MIDCPNIFTY.
  - Computes Black-Scholes Greeks: Delta, Implied Volatility (IV), ATM strike highlighting, ITM/OTM classification, and live strike selection.
- **Index Futures & Spot Index Protection**:
  - Spot Indices (NIFTY 50, BANK NIFTY, SENSEX, FINNIFTY) are displayed as non-tradable `SPOT` references.
  - Official Index Futures (`NIFTY-FUT`, `BANKNIFTY-FUT`, `SENSEX-FUT`, `FINNIFTY-FUT`) with exchange lot sizes (65, 30, 20, 60) and 12% margin calculation.
- **Dynamic Watchlist & Search**:
  - Clean filter tabs: **`Indices`**, **`Futures`**, and **`Stocks`**.
  - Interactive search bar with instant dropdown to find and `+ Add` any Indian stock or future to your watchlist.
  - Persistent watchlist storage via `localStorage`.
- **World-Class Mobile & Desktop UI**:
  - Responsive bottom navigation, bottom sheets, safe area padding, dark theme, and intuitive 1-click `[B]` and `[S]` order buttons.

---

## Quick Start (Local)

### Prerequisites
- Python 3.10+ installed

### Windows
Double-click `start.bat` or run in terminal:
```bash
python start.py
```

### Linux / macOS
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m backend.server
```

Open your browser at **http://127.0.0.1:8000**.

---

## 24/7 Cloud Deployment

This repository is pre-configured for one-click 24/7 deployment on any cloud provider:

### Option 1: Docker
```bash
docker build -t instatrade .
docker run -p 8000:8000 instatrade
```

### Option 2: Render / Railway / Fly.io / Heroku
1. Fork or push this repository to GitHub (`extraid5607/InstaTrade`).
2. Create a new **Web Service** pointing to your repository.
3. The platform will automatically detect `Procfile` or `Dockerfile` and launch:
   ```bash
   uvicorn backend.server:app --host 0.0.0.0 --port $PORT
   ```

---

## License & Disclaimer
This software is built for educational, simulation, and virtual paper trading purposes. Market data is streamed for simulation and testing.

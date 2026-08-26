# CryptoPulse

A Flask web app for tracking live cryptocurrency prices, managing a personal
watchlist, and simulating a crypto portfolio — built with Python, Flask,
SQLite, and the free [CoinGecko API](https://www.coingecko.com/en/api).

## Features

- **User authentication** — register/login with hashed passwords (`werkzeug.security`) and Flask sessions
- **Live market dashboard** — real-time prices, 24h % change (color-coded), and market cap for top coins
- **Watchlist** — add/remove coins from a personal watchlist (no duplicates, enforced at the DB level)
- **Portfolio simulator** — record how much of a coin you hold and see the live USD value update
- **Resilient API layer** — 60-second in-memory cache to avoid CoinGecko rate limits, with graceful fallback messaging if the API is down
- **Dark mode UI** — clean, responsive, card-based design

## Setup

1. **Install dependencies** (Python 3.9+ recommended):

   ```bash
   pip install -r requirements.txt
   ```

2. **Run the app** — the SQLite database and tables are created automatically on first run:

   ```bash
   python app.py
   ```

3. Open your browser to **http://127.0.0.1:5000**

4. Register an account, then explore the Dashboard, Watchlist, and Portfolio pages.

## Project Structure

```
cryptopulse/
├── app.py               # Flask routes, auth, DB setup
├── helpers.py            # login_required, CoinGecko fetch + cache, formatting filters
├── requirements.txt
├── cryptopulse.db         # created automatically on first run
├── static/
│   └── styles.css
└── templates/
    ├── layout.html
    ├── login.html
    ├── register.html
    ├── dashboard.html
    ├── watchlist.html
    └── portfolio.html
```

## Notes

- The database file (`cryptopulse.db`) is created the first time you run `python app.py`. Delete it any time to start fresh.
- The CoinGecko free public API doesn't require an API key, but it is rate-limited — the built-in 60-second cache keeps normal browsing well within limits.
- To add more coins to the "add to watchlist / portfolio" dropdowns, add entries to `COIN_CATALOG` in `helpers.py` using valid [CoinGecko coin IDs](https://api.coingecko.com/api/v3/coins/list).
- Change `app.secret_key` in `app.py` before deploying this anywhere beyond your own machine.

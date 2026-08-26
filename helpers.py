"""
Helper functions for CryptoPulse:
 - login_required decorator
 - CoinGecko API fetching with a simple in-memory cache to avoid 429 errors
 - Jinja formatting filters for currency and quantities
"""

import time
from functools import wraps

import requests
from flask import redirect, session, url_for

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_OHLC_URL = "https://api.coingecko.com/api/v3/coins/{id}/ohlc"
CACHE_DURATION_SECONDS = 60

# In-memory cache: keyed by a sorted tuple of coin ids, so different pages
# requesting different coin sets don't stomp on each other.
_cache = {}

# Separate in-memory cache for OHLC (candlestick) data, keyed by (coin_id, days).
_ohlc_cache = {}

# Selectable candlestick chart ranges. CoinGecko auto-picks candle width
# based on the "days" value (30-min candles for 1-14 days, 4-hour for
# 30-90 days, 4-day for 180-365 days).
CHART_RANGES = {
    "1": "1D",
    "7": "7D",
    "14": "14D",
    "30": "30D",
    "90": "90D",
    "180": "180D",
    "365": "1Y",
}


# ---------------------------------------------------------------------------
# A small static catalog of coins supported by the app for the
# watchlist / portfolio "add coin" dropdowns.
# ---------------------------------------------------------------------------
COIN_CATALOG = {
    "bitcoin": {"name": "Bitcoin", "symbol": "BTC"},
    "ethereum": {"name": "Ethereum", "symbol": "ETH"},
    "solana": {"name": "Solana", "symbol": "SOL"},
    "cardano": {"name": "Cardano", "symbol": "ADA"},
    "ripple": {"name": "XRP", "symbol": "XRP"},
    "dogecoin": {"name": "Dogecoin", "symbol": "DOGE"},
    "polkadot": {"name": "Polkadot", "symbol": "DOT"},
    "litecoin": {"name": "Litecoin", "symbol": "LTC"},
    "chainlink": {"name": "Chainlink", "symbol": "LINK"},
    "avalanche-2": {"name": "Avalanche", "symbol": "AVAX"},
    "binancecoin": {"name": "BNB", "symbol": "BNB"},
    "tron": {"name": "TRON", "symbol": "TRX"},
    "matic-network": {"name": "Polygon", "symbol": "MATIC"},
    "uniswap": {"name": "Uniswap", "symbol": "UNI"},
    "stellar": {"name": "Stellar", "symbol": "XLM"},
}


def login_required(f):
    """Decorate routes that require the user to be logged in."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def fetch_market_data(coin_ids):
    """Fetch live market data for the given list of CoinGecko coin ids.

    Uses a short-lived in-memory cache (CACHE_DURATION_SECONDS) so repeated
    page loads within the same window don't hammer the free CoinGecko API
    and trigger 429 Too Many Requests errors.

    Returns a tuple: (list_of_coin_dicts, error_message_or_None)
    On any network failure, returns ([], friendly_error_message) instead
    of raising, so callers never need to worry about the app crashing.
    """
    if not coin_ids:
        return [], None

    cache_key = tuple(sorted(coin_ids))
    now = time.time()

    cached = _cache.get(cache_key)
    if cached and (now - cached["timestamp"] < CACHE_DURATION_SECONDS):
        return cached["data"], None

    params = {
        "vs_currency": "usd",
        "ids": ",".join(coin_ids),
        "order": "market_cap_desc",
        "price_change_percentage": "24h",
    }

    try:
        response = requests.get(COINGECKO_URL, params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException:
        # Network error, timeout, DNS failure, 4xx/5xx, etc.
        # Fall back to a stale cache if we have one, otherwise show an error.
        if cached:
            return cached["data"], (
                "Live prices may be out of date — showing the last "
                "successful update."
            )
        return [], "Unable to fetch live market data right now. Please try again later."
    except ValueError:
        # response.json() failed to parse
        if cached:
            return cached["data"], (
                "Live prices may be out of date — showing the last "
                "successful update."
            )
        return [], "Unable to fetch live market data right now. Please try again later."

    _cache[cache_key] = {"data": data, "timestamp": now}
    return data, None


def fetch_ohlc_data(coin_id, days="7"):
    """Fetch OHLC (open/high/low/close) candlestick data for a single coin
    from CoinGecko's /coins/{id}/ohlc endpoint.

    Cached the same way as fetch_market_data to avoid rate limits. Returns
    a tuple: (list_of_[timestamp_ms, open, high, low, close], error_or_None).
    Never raises — network/parsing failures degrade to a friendly message
    (or a stale cached chart, if one is available).
    """
    cache_key = (coin_id, str(days))
    now = time.time()

    cached = _ohlc_cache.get(cache_key)
    if cached and (now - cached["timestamp"] < CACHE_DURATION_SECONDS):
        return cached["data"], None

    url = COINGECKO_OHLC_URL.format(id=coin_id)
    params = {"vs_currency": "usd", "days": days}

    try:
        response = requests.get(url, params=params, timeout=8)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException:
        if cached:
            return cached["data"], (
                "Chart data may be out of date — showing the last "
                "successful update."
            )
        return [], "Unable to fetch chart data right now. Please try again later."
    except ValueError:
        if cached:
            return cached["data"], (
                "Chart data may be out of date — showing the last "
                "successful update."
            )
        return [], "Unable to fetch chart data right now. Please try again later."

    _ohlc_cache[cache_key] = {"data": data, "timestamp": now}
    return data, None


def usd(value):
    """Format a number as US dollars with commas and appropriate decimal
    places. Coins under $1 get more decimal places so small prices (e.g.
    Dogecoin at $0.08123) don't round away to $0.00 or $0.08."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "$0.00"

    if value == 0:
        return "$0.00"
    if abs(value) < 1:
        return f"${value:,.4f}"
    return f"${value:,.2f}"


def format_qty(value):
    """Format a coin quantity cleanly, trimming trailing zeros while
    avoiding floating-point display artifacts like 0.30000000000000004."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"

    text = f"{value:.8f}".rstrip("0").rstrip(".")
    return text if text else "0"

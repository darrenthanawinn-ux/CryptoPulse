"""
CryptoPulse - A Flask web app for tracking cryptocurrency prices,
managing a personal watchlist, and simulating a portfolio.
"""

import sqlite3
from datetime import datetime

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import (
    login_required,
    fetch_market_data,
    fetch_ohlc_data,
    usd,
    format_qty,
    COIN_CATALOG,
    CHART_RANGES,
)

app = Flask(__name__)
app.secret_key = "cryptopulse-dev-secret-key-change-me"  # change in production

DATABASE = "cryptopulse.db"

# Register Jinja filters so templates can format numbers cleanly
app.jinja_env.filters["usd"] = usd
app.jinja_env.filters["qty"] = format_qty


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    """Open a new database connection if there isn't one for the current
    application context, and return a connection with row access by name."""
    db = getattr(g, "_database", None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, "_database", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables if they do not already exist."""
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                coin_id TEXT NOT NULL,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, coin_id)
            );

            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                coin_id TEXT NOT NULL,
                amount REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, coin_id)
            );
            """
        )
        db.commit()


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("confirmation", "")

        if not username:
            flash("Username is required.", "error")
            return render_template("register.html")
        if not password or len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")
        if password != confirmation:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            flash("That username is already taken.", "error")
            return render_template("register.html")

        password_hash = generate_password_hash(password)
        db.execute(
            "INSERT INTO users (username, hash) VALUES (?, ?)",
            (username, password_hash),
        )
        db.commit()

        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    session.clear()

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("login.html")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()

        if user is None or not check_password_hash(user["hash"], password):
            flash("Invalid username and/or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        flash(f"Welcome back, {user['username']}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def dashboard():
    default_ids = ["bitcoin", "ethereum", "solana", "cardano"]
    market_data, error = fetch_market_data(default_ids)

    return render_template(
        "dashboard.html",
        coins=market_data,
        error=error,
        last_updated=datetime.now().strftime("%I:%M:%S %p"),
    )


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------
@app.route("/watchlist", methods=["GET", "POST"])
@login_required
def watchlist():
    db = get_db()
    user_id = session["user_id"]

    if request.method == "POST":
        coin_id = request.form.get("coin_id", "").strip().lower()

        if not coin_id or coin_id not in COIN_CATALOG:
            flash("Please choose a valid coin.", "error")
            return redirect(url_for("watchlist"))

        try:
            db.execute(
                "INSERT INTO watchlist (user_id, coin_id) VALUES (?, ?)",
                (user_id, coin_id),
            )
            db.commit()
            flash(f"{COIN_CATALOG[coin_id]['name']} added to your watchlist.", "success")
        except sqlite3.IntegrityError:
            # UNIQUE(user_id, coin_id) constraint stops duplicates
            flash("That coin is already on your watchlist.", "error")

        return redirect(url_for("watchlist"))

    rows = db.execute(
        "SELECT coin_id FROM watchlist WHERE user_id = ? ORDER BY added_at DESC",
        (user_id,),
    ).fetchall()
    watch_ids = [row["coin_id"] for row in rows]

    market_data, error = ([], None)
    if watch_ids:
        market_data, error = fetch_market_data(watch_ids)

    # Coins not yet on the watchlist, for the "add" dropdown
    available_coins = {
        cid: info for cid, info in COIN_CATALOG.items() if cid not in watch_ids
    }

    return render_template(
        "watchlist.html",
        coins=market_data,
        error=error,
        available_coins=available_coins,
    )


@app.route("/watchlist/remove", methods=["POST"])
@login_required
def watchlist_remove():
    coin_id = request.form.get("coin_id", "").strip().lower()
    db = get_db()
    db.execute(
        "DELETE FROM watchlist WHERE user_id = ? AND coin_id = ?",
        (session["user_id"], coin_id),
    )
    db.commit()
    flash("Removed from watchlist.", "success")
    return redirect(url_for("watchlist"))


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------
@app.route("/portfolio", methods=["GET", "POST"])
@login_required
def portfolio():
    db = get_db()
    user_id = session["user_id"]

    if request.method == "POST":
        coin_id = request.form.get("coin_id", "").strip().lower()
        amount_raw = request.form.get("amount", "").strip()

        if not coin_id or coin_id not in COIN_CATALOG:
            flash("Please choose a valid coin.", "error")
            return redirect(url_for("portfolio"))

        try:
            amount = float(amount_raw)
        except ValueError:
            flash("Amount must be a number.", "error")
            return redirect(url_for("portfolio"))

        if amount <= 0:
            flash("Amount must be greater than zero.", "error")
            return redirect(url_for("portfolio"))

        # Upsert: if the user already holds this coin, add to their existing amount
        existing = db.execute(
            "SELECT amount FROM portfolio WHERE user_id = ? AND coin_id = ?",
            (user_id, coin_id),
        ).fetchone()

        if existing:
            new_amount = round(existing["amount"] + amount, 8)
            db.execute(
                "UPDATE portfolio SET amount = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ? AND coin_id = ?",
                (new_amount, user_id, coin_id),
            )
        else:
            db.execute(
                "INSERT INTO portfolio (user_id, coin_id, amount) VALUES (?, ?, ?)",
                (user_id, coin_id, round(amount, 8)),
            )
        db.commit()
        flash(f"Updated your {COIN_CATALOG[coin_id]['name']} holdings.", "success")
        return redirect(url_for("portfolio"))

    rows = db.execute(
        "SELECT coin_id, amount FROM portfolio WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,),
    ).fetchall()
    holdings_by_coin = {row["coin_id"]: row["amount"] for row in rows}

    market_data, error = ([], None)
    if holdings_by_coin:
        market_data, error = fetch_market_data(list(holdings_by_coin.keys()))

    holdings = []
    total_value = 0.0
    if not error:
        for coin in market_data:
            amount = holdings_by_coin.get(coin["id"], 0)
            value = amount * coin["current_price"]
            total_value += value
            holdings.append(
                {
                    "id": coin["id"],
                    "name": coin["name"],
                    "symbol": coin["symbol"],
                    "image": coin["image"],
                    "amount": amount,
                    "price": coin["current_price"],
                    "value": value,
                }
            )
        holdings.sort(key=lambda h: h["value"], reverse=True)

    return render_template(
        "portfolio.html",
        holdings=holdings,
        total_value=total_value,
        error=error,
        available_coins=COIN_CATALOG,
    )


@app.route("/portfolio/remove", methods=["POST"])
@login_required
def portfolio_remove():
    coin_id = request.form.get("coin_id", "").strip().lower()
    db = get_db()
    db.execute(
        "DELETE FROM portfolio WHERE user_id = ? AND coin_id = ?",
        (session["user_id"], coin_id),
    )
    db.commit()
    flash("Holding removed.", "success")
    return redirect(url_for("portfolio"))


# ---------------------------------------------------------------------------
# Markets table + candlestick charts
# ---------------------------------------------------------------------------
@app.route("/markets")
@login_required
def markets():
    """A table of every currency built into the app's catalog, each linking
    to its own live candlestick chart."""
    all_ids = list(COIN_CATALOG.keys())
    market_data, error = fetch_market_data(all_ids)

    # Preserve COIN_CATALOG's order rather than whatever order the API returns
    by_id = {coin["id"]: coin for coin in market_data}
    ordered_coins = [by_id[cid] for cid in COIN_CATALOG if cid in by_id]

    return render_template("markets.html", coins=ordered_coins, error=error)


@app.route("/chart/<coin_id>")
@login_required
def chart(coin_id):
    coin_id = coin_id.strip().lower()
    if coin_id not in COIN_CATALOG:
        flash("Unknown coin.", "error")
        return redirect(url_for("markets"))

    days = request.args.get("days", "7")
    if days not in CHART_RANGES:
        days = "7"

    ohlc_data, error = fetch_ohlc_data(coin_id, days=days)

    return render_template(
        "chart.html",
        coin_id=coin_id,
        coin_info=COIN_CATALOG[coin_id],
        ohlc_data=ohlc_data,
        error=error,
        selected_range=days,
        ranges=CHART_RANGES,
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)

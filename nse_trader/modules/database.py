"""
Database initialization and management.
Uses SQLite for simplicity and portability on Windows.
"""

import sqlite3
import os
import sys
from datetime import datetime

# Ensure project root is on the path so 'config' can be imported from modules/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DB_PATH, DATA_DIR


def get_connection():
    """Get a database connection with row factory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_database():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    # ── Price data ────────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            adj_close REAL,
            PRIMARY KEY (symbol, date)
        )
    """)

    # ── Fundamental data (quarterly refresh) ──────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fundamentals (
            symbol TEXT PRIMARY KEY,
            market_cap_cr REAL,
            pe_ratio REAL,
            pb_ratio REAL,
            roe REAL,
            roce REAL,
            debt_equity REAL,
            promoter_holding REAL,
            promoter_pledge REAL,
            fii_holding REAL,
            dii_holding REAL,
            revenue_growth_yoy REAL,
            profit_growth_yoy REAL,
            operating_margin REAL,
            free_cash_flow_cr REAL,
            dividend_yield REAL,
            current_ratio REAL,
            sector TEXT,
            industry TEXT,
            last_updated TEXT
        )
    """)

    # ── News headlines and scores ─────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            headline TEXT NOT NULL,
            source TEXT,
            url TEXT,
            published_date TEXT,
            fetched_date TEXT DEFAULT (datetime('now')),
            sentiment TEXT,
            sentiment_score REAL DEFAULT 0,
            magnitude INTEGER DEFAULT 1,
            category TEXT,
            is_processed INTEGER DEFAULT 0
        )
    """)

    # ── Market macro data ─────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS macro_data (
            date TEXT PRIMARY KEY,
            nifty_close REAL,
            nifty_change_pct REAL,
            banknifty_close REAL,
            banknifty_change_pct REAL,
            india_vix REAL,
            fii_net_cr REAL,
            dii_net_cr REAL,
            usd_inr REAL,
            crude_brent REAL,
            sp500_close REAL,
            sp500_change_pct REAL,
            nasdaq_change_pct REAL,
            us_10y_yield REAL,
            gift_nifty REAL,
            gift_nifty_change_pct REAL
        )
    """)

    # ── Technical scores (daily computed) ─────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS technical_scores (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            ema_20 REAL,
            ema_50 REAL,
            rsi_14 REAL,
            macd_line REAL,
            macd_signal REAL,
            macd_histogram REAL,
            atr_14 REAL,
            volume_ratio REAL,
            relative_strength REAL,
            breakout_detected INTEGER DEFAULT 0,
            breakout_level REAL,
            technical_score REAL DEFAULT 0,
            score_breakdown TEXT,
            PRIMARY KEY (symbol, date)
        )
    """)

    # ── Daily recommendations ─────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT DEFAULT 'BUY',
            entry_low REAL,
            entry_high REAL,
            target_price REAL,
            stop_loss REAL,
            quantity INTEGER,
            position_value REAL,
            risk_amount REAL,
            reward_amount REAL,
            risk_reward_ratio REAL,
            expected_holding TEXT,
            composite_score REAL,
            news_score REAL,
            technical_score REAL,
            fundamental_score REAL,
            market_score REAL,
            confidence TEXT,
            reasoning TEXT,
            news_trigger TEXT,
            technical_setup TEXT,
            key_risks TEXT,
            exit_rules TEXT,
            status TEXT DEFAULT 'PENDING',
            UNIQUE(date, symbol)
        )
    """)

    # ── Rejected stocks log ───────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rejected_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            composite_score REAL,
            rejection_reason TEXT,
            UNIQUE(date, symbol)
        )
    """)

    # ── Trade journal ─────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
            trade_id TEXT PRIMARY KEY,
            date_entry TEXT NOT NULL,
            date_exit TEXT,
            symbol TEXT NOT NULL,
            direction TEXT DEFAULT 'LONG',
            entry_price REAL NOT NULL,
            exit_price REAL,
            quantity INTEGER NOT NULL,
            gross_pnl REAL,
            brokerage_taxes REAL,
            net_pnl REAL,
            risk_amount_planned REAL,
            r_multiple REAL,
            composite_score_at_entry REAL,
            exit_reason TEXT,
            holding_days INTEGER,
            emotional_state TEXT,
            what_went_right TEXT,
            what_went_wrong TEXT,
            lesson TEXT,
            status TEXT DEFAULT 'OPEN'
        )
    """)

    # ── Market health log ─────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS market_health (
            date TEXT PRIMARY KEY,
            market_score REAL,
            verdict TEXT,
            nifty_trend TEXT,
            banknifty_trend TEXT,
            vix_level TEXT,
            fii_stance TEXT,
            global_cue TEXT,
            details TEXT
        )
    """)

    # ── System run log ────────────────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT (datetime('now')),
            module TEXT,
            level TEXT,
            message TEXT
        )
    """)

    # ── Daily portfolio snapshot ──────────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            date TEXT PRIMARY KEY,
            total_capital REAL,
            deployed_capital REAL,
            cash_available REAL,
            open_positions INTEGER,
            daily_pnl REAL,
            cumulative_pnl REAL,
            drawdown_pct REAL,
            win_count INTEGER DEFAULT 0,
            loss_count INTEGER DEFAULT 0,
            total_trades INTEGER DEFAULT 0
        )
    """)

    # ── Bulk / Block deals (institutional footprint) ──────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bulk_deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_type TEXT,
            symbol TEXT,
            client_name TEXT,
            buy_sell TEXT,
            quantity INTEGER,
            price REAL,
            value_cr REAL,
            deal_date TEXT,
            fetched_date TEXT DEFAULT (date('now')),
            UNIQUE(deal_type, symbol, client_name, deal_date)
        )
    """)

    # ── Short trade recommendations ───────────────────────────────────────
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS short_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry_low REAL,
            entry_high REAL,
            target_price REAL,
            stop_loss REAL,
            lot_size INTEGER,
            margin_required REAL,
            risk_amount REAL,
            reward_amount REAL,
            risk_reward_ratio REAL,
            composite_score REAL,
            short_score REAL,
            confidence TEXT,
            reasoning TEXT,
            bearish_catalyst TEXT,
            technical_weakness TEXT,
            key_risks TEXT,
            exit_rules TEXT,
            UNIQUE(date, symbol)
        )
    """)

    conn.commit()
    conn.close()
    return True


def log_system_event(module: str, level: str, message: str):
    """Log a system event."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO system_log (module, level, message) VALUES (?, ?, ?)",
        (module, level, message)
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_database()
    print(f"Database initialized at {DB_PATH}")

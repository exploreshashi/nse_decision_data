"""
Data Fetching Module
Fetches OHLCV, macro, FII/DII, bulk/block deals, and corporate announcements.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time as time_module
import json
import sys
import os

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    STOCK_UNIVERSE, NIFTY_SYMBOL, BANKNIFTY_SYMBOL, INDIA_VIX_SYMBOL,
    MIN_AVG_TURNOVER_CR, MIN_PRICE, MAX_PRICE, FNO_CACHE_PATH, FNO_LOTS_URL,
)
from modules.database import get_connection, log_system_event


# ─── Batch price fetch ────────────────────────────────────────────────────────

def fetch_stock_prices(symbols: list = None, period: str = "6mo",
                       chunk_size: int = 50) -> dict:
    """
    Fetch OHLCV data for given symbols from yfinance using yf.download's batched,
    multi-threaded API (one request per chunk instead of one per symbol).

    This is dramatically faster than per-ticker .history() calls and makes far
    fewer requests to Yahoo, which also reduces rate-limiting on cloud hosts.

    Returns dict of {symbol: DataFrame}.
    """
    if symbols is None:
        symbols = STOCK_UNIVERSE

    # De-duplicate while preserving order
    seen = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]

    results = {}
    failed  = []
    sym_map = {f"{s}.NS": s for s in symbols}
    tickers = list(sym_map.keys())
    keep    = ['open', 'high', 'low', 'close', 'volume']

    def _clean(df, sym):
        try:
            if df is None or df.empty:
                return None
            df = df.dropna(how='all')
            df.columns = [str(c).lower() for c in df.columns]
            if 'close' not in df.columns:
                return None
            df = df.dropna(subset=['close'])
            if len(df) <= 10:
                return None
            df.index = pd.to_datetime(df.index)
            cols = [c for c in keep if c in df.columns]
            return df[cols]
        except Exception:
            return None

    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            data = yf.download(
                tickers=chunk, period=period, interval="1d",
                group_by="ticker", auto_adjust=True,
                threads=True, progress=False,
            )
        except Exception as e:
            log_system_event("data_fetcher", "WARNING", f"yf.download chunk failed: {e}")
            data = None

        if data is None or len(data) == 0:
            failed.extend(sym_map[t] for t in chunk)
            continue

        # Single-ticker chunks return a flat (non-grouped) frame
        is_multi = hasattr(data.columns, "levels") and len(chunk) > 1
        for t in chunk:
            sym = sym_map[t]
            try:
                df = data[t] if (is_multi and t in data.columns.get_level_values(0)) else (
                    data if not is_multi else None
                )
            except Exception:
                df = None
            cleaned = _clean(df, sym)
            if cleaned is not None:
                results[sym] = cleaned
            else:
                failed.append(sym)

    log_system_event(
        "data_fetcher", "INFO",
        f"Batch fetch: {len(results)}/{len(symbols)} stocks OK. Failed: {len(failed)}"
    )
    return results


def store_prices(price_data: dict):
    """Store fetched price data into SQLite (single batched transaction)."""
    rows = []
    for symbol, df in price_data.items():
        for date_idx, row in df.iterrows():
            try:
                close = round(float(row.get('close', 0)), 2)
                rows.append((
                    symbol, date_idx.strftime('%Y-%m-%d'),
                    round(float(row.get('open', 0)), 2),
                    round(float(row.get('high', 0)), 2),
                    round(float(row.get('low', 0)), 2),
                    close,
                    int(row.get('volume', 0) or 0),
                    close,
                ))
            except Exception:
                continue

    conn = get_connection()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO prices
            (symbol, date, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, rows)
        conn.commit()
    finally:
        conn.close()

    log_system_event("data_fetcher", "INFO", f"Stored {len(rows)} price records")
    return len(rows)


# ─── NSE reachability probe (cloud vs local) ─────────────────────────────────

_NSE_REACHABLE = None   # process-level cache: None=unknown, True/False

def nse_reachable() -> bool:
    """
    Return True if nseindia.com responds quickly. NSE geo-blocks datacenter IPs,
    so on Streamlit Cloud / overseas hosts this returns False — letting NSE-backed
    features (FII/DII, bulk deals, live F&O list) skip fast instead of hanging on
    long timeouts. Result is cached for the process lifetime.
    """
    global _NSE_REACHABLE
    if _NSE_REACHABLE is not None:
        return _NSE_REACHABLE
    if not HAS_REQUESTS:
        _NSE_REACHABLE = False
        return False
    try:
        r = requests.get(
            "https://www.nseindia.com",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=4,
        )
        _NSE_REACHABLE = (r.status_code == 200)
    except Exception:
        _NSE_REACHABLE = False
    log_system_event("data_fetcher", "INFO",
                     f"NSE reachable: {_NSE_REACHABLE}")
    return _NSE_REACHABLE


# ─── Live F&O universe (NSE lot-size file) ───────────────────────────────────

def get_fno_universe(force: bool = False) -> tuple:
    """
    Return (symbols, lot_sizes) for the full NSE F&O underlying universe.

    Source of truth is the NSE F&O market-lots CSV (FNO_LOTS_URL), cached to
    FNO_CACHE_PATH for 7 days. Falls back to the static STOCK_UNIVERSE (and empty
    lot sizes) when NSE is unreachable — e.g. on cloud hosts.

    Returns:
        (list_of_symbols, {symbol: lot_size})
    """
    import json

    # 1. Try fresh cache
    if not force and os.path.exists(FNO_CACHE_PATH):
        try:
            with open(FNO_CACHE_PATH, encoding="utf-8") as f:
                cached = json.load(f)
            ts = datetime.strptime(cached.get("date", "2000-01-01"), "%Y-%m-%d")
            if (datetime.now() - ts).days < 7 and cached.get("symbols"):
                return cached["symbols"], cached.get("lots", {})
        except Exception:
            pass

    # 2. Try live NSE fetch (only worth attempting when NSE is reachable)
    if HAS_REQUESTS and nse_reachable():
        try:
            resp = requests.get(
                FNO_LOTS_URL,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                timeout=10,
            )
            if resp.status_code == 200 and resp.text:
                symbols, lots = _parse_fno_lots(resp.text)
                if len(symbols) >= 50:
                    try:
                        os.makedirs(os.path.dirname(FNO_CACHE_PATH), exist_ok=True)
                        with open(FNO_CACHE_PATH, "w", encoding="utf-8") as f:
                            json.dump({
                                "date":    datetime.now().strftime("%Y-%m-%d"),
                                "symbols": symbols,
                                "lots":    lots,
                            }, f)
                    except Exception:
                        pass
                    log_system_event("data_fetcher", "INFO",
                                     f"Live F&O universe: {len(symbols)} symbols")
                    return symbols, lots
        except Exception as e:
            log_system_event("data_fetcher", "WARNING", f"F&O list fetch failed: {e}")

    # 3. Fallback to static universe
    return list(STOCK_UNIVERSE), {}


def get_lot_size(symbol: str, default: int = 500) -> int:
    """Return the F&O lot size for a symbol from the cached NSE lot file."""
    import json
    try:
        if os.path.exists(FNO_CACHE_PATH):
            with open(FNO_CACHE_PATH, encoding="utf-8") as f:
                lots = json.load(f).get("lots", {})
            v = lots.get(symbol.upper())
            if v:
                return int(v)
    except Exception:
        pass
    return default


def _parse_fno_lots(csv_text: str) -> tuple:
    """Parse the NSE fo_mktlots.csv into (symbols, {symbol: lot_size})."""
    symbols, lots = [], {}
    lines = [ln for ln in csv_text.splitlines() if ln.strip()]
    if not lines:
        return symbols, lots

    header = [h.strip().upper() for h in lines[0].split(",")]
    try:
        sym_idx = next(i for i, h in enumerate(header) if "SYMBOL" in h)
    except StopIteration:
        sym_idx = 1
    # First numeric lot column after the symbol column = nearest expiry lot size
    lot_idx = sym_idx + 1

    EXCLUDE = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
               "SYMBOL", "UNDERLYING"}
    for ln in lines[1:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) <= sym_idx:
            continue
        sym = parts[sym_idx].upper()
        if not sym or sym in EXCLUDE:
            continue
        symbols.append(sym)
        try:
            lots[sym] = int(float(parts[lot_idx]))
        except (ValueError, IndexError):
            pass
    # De-duplicate, preserve order
    seen = set()
    symbols = [s for s in symbols if not (s in seen or seen.add(s))]
    return symbols, lots


def fetch_index_data(period: str = "6mo") -> dict:
    """Fetch Nifty, Bank Nifty, VIX data."""
    indices = {
        'NIFTY': NIFTY_SYMBOL,
        'BANKNIFTY': BANKNIFTY_SYMBOL,
        'VIX': INDIA_VIX_SYMBOL
    }
    results = {}

    for name, symbol in indices.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
            if not df.empty:
                df.columns = [c.lower() for c in df.columns]
                results[name] = df
        except Exception as e:
            log_system_event("data_fetcher", "WARNING", f"Failed to fetch {name}: {e}")

    return results


def fetch_global_data(period: str = "1mo") -> dict:
    """Fetch global market indicators."""
    global_tickers = {
        'SP500': '^GSPC',
        'NASDAQ': '^IXIC',
        'CRUDE': 'BZ=F',       # Brent crude
        'USDINR': 'INR=X',
        'US10Y': '^TNX',
        'GOLD': 'GC=F',
    }
    results = {}

    for name, symbol in global_tickers.items():
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period)
            if not df.empty:
                df.columns = [c.lower() for c in df.columns]
                results[name] = df
        except Exception as e:
            log_system_event("data_fetcher", "WARNING", f"Failed to fetch {name}: {e}")

    return results


def store_macro_data(index_data: dict, global_data: dict):
    """Store macro data into database."""
    conn = get_connection()
    cursor = conn.cursor()

    # Get latest date from Nifty data
    nifty_df = index_data.get('NIFTY')
    if nifty_df is None or nifty_df.empty:
        conn.close()
        return

    for date_idx, row in nifty_df.iterrows():
        date_str = date_idx.strftime('%Y-%m-%d')
        nifty_close = float(row['close'])
        nifty_prev = float(nifty_df['close'].shift(1).loc[date_idx]) if date_idx != nifty_df.index[0] else nifty_close
        nifty_chg = ((nifty_close - nifty_prev) / nifty_prev * 100) if nifty_prev else 0

        bn_close = bn_chg = vix = sp_close = sp_chg = nasdaq_chg = None
        crude = usdinr = us10y = None

        if 'BANKNIFTY' in index_data and date_idx in index_data['BANKNIFTY'].index:
            bn_row = index_data['BANKNIFTY'].loc[date_idx]
            bn_close = float(bn_row['close'])

        if 'VIX' in index_data and date_idx in index_data['VIX'].index:
            vix = float(index_data['VIX'].loc[date_idx]['close'])

        # Global data - find nearest date
        for gname, gkey, target in [
            ('SP500', 'close', 'sp_close'),
            ('CRUDE', 'close', 'crude'),
            ('USDINR', 'close', 'usdinr'),
            ('US10Y', 'close', 'us10y'),
        ]:
            if gname in global_data and not global_data[gname].empty:
                gdf = global_data[gname]
                # Find nearest date within 3 days
                mask = abs((gdf.index - date_idx).days) <= 3
                if mask.any():
                    nearest = gdf[mask].iloc[-1]
                    if target == 'sp_close':
                        sp_close = float(nearest['close'])
                    elif target == 'crude':
                        crude = float(nearest['close'])
                    elif target == 'usdinr':
                        usdinr = float(nearest['close'])
                    elif target == 'us10y':
                        us10y = float(nearest['close'])

        try:
            cursor.execute("""
                INSERT OR REPLACE INTO macro_data 
                (date, nifty_close, nifty_change_pct, banknifty_close,
                 india_vix, sp500_close, crude_brent, usd_inr, us_10y_yield)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str, nifty_close, round(nifty_chg, 2), bn_close,
                vix, sp_close, crude, usdinr, us10y
            ))
        except Exception:
            continue

    conn.commit()
    conn.close()


def get_price_dataframe(symbol: str, days: int = 120) -> pd.DataFrame:
    """Get price data from database as DataFrame."""
    conn = get_connection()
    query = """
        SELECT date, open, high, low, close, volume 
        FROM prices 
        WHERE symbol = ? 
        ORDER BY date DESC 
        LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=(symbol, days))
    conn.close()

    if df.empty:
        return df

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    return df


def get_latest_macro() -> dict:
    """Get the most recent macro data."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM macro_data ORDER BY date DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return {}

    return dict(row)


def filter_liquid_stocks(price_data: dict) -> list:
    """Filter stocks by liquidity (avg turnover > threshold)."""
    liquid = []

    for symbol, df in price_data.items():
        if len(df) < 20:
            continue

        # Approximate turnover = close * volume
        recent = df.tail(20)
        avg_turnover = (recent['close'] * recent['volume']).mean()
        avg_turnover_cr = avg_turnover / 1e7  # Convert to crores

        last_price = float(df['close'].iloc[-1])

        if (avg_turnover_cr >= MIN_AVG_TURNOVER_CR and
            last_price >= MIN_PRICE and
            last_price <= MAX_PRICE):
            liquid.append(symbol)

    return liquid


def run_data_pipeline():
    """Run the full data ingestion pipeline."""
    log_system_event("data_fetcher", "INFO", "Starting data pipeline")
    start = datetime.now()

    # 1. Fetch stock prices
    print("📊 Fetching stock prices...")
    price_data = fetch_stock_prices()
    if price_data:
        store_prices(price_data)
        print(f"  ✅ Fetched {len(price_data)} stocks")
    else:
        print("  ❌ No stock data fetched")
        return False

    # 2. Fetch index data
    print("📈 Fetching index data...")
    index_data = fetch_index_data()
    print(f"  ✅ Fetched {len(index_data)} indices")

    # 3. Fetch global data
    print("🌍 Fetching global data...")
    global_data = fetch_global_data()
    print(f"  ✅ Fetched {len(global_data)} global indicators")

    # 4. Store macro data
    if index_data:
        store_macro_data(index_data, global_data)
        print("  ✅ Macro data stored")

    elapsed = (datetime.now() - start).seconds
    log_system_event("data_fetcher", "INFO", f"Pipeline completed in {elapsed}s")
    print(f"\n✅ Data pipeline completed in {elapsed} seconds")

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# FII / DII  —  NSE public API
# ═══════════════════════════════════════════════════════════════════════════════

def _nse_session() -> "requests.Session":
    """Return a warmed-up requests.Session that NSE accepts."""
    s = requests.Session()
    s.headers.update({
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/124.0.0.0 Safari/537.36'
        ),
        'Accept':          'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer':         'https://www.nseindia.com/',
        'Connection':      'keep-alive',
    })
    try:
        s.get('https://www.nseindia.com', timeout=6)
        time_module.sleep(0.8)
    except Exception:
        pass
    return s


def fetch_fii_dii_data() -> dict:
    """
    Fetch today's FII / DII net cash-market flows from NSE.
    Returns dict with keys: fii_buy_cr, fii_sell_cr, fii_net_cr,
                             dii_buy_cr, dii_sell_cr, dii_net_cr, date.
    Falls back to an empty dict on any error.
    """
    if not HAS_REQUESTS:
        log_system_event("data_fetcher", "WARNING", "requests not installed — cannot fetch FII/DII")
        return {}

    # NSE geo-blocks cloud IPs — skip fast instead of hanging on timeouts.
    if not nse_reachable():
        log_system_event("data_fetcher", "INFO", "NSE unreachable — skipping FII/DII")
        return {}

    try:
        session = _nse_session()
        resp = session.get(
            'https://www.nseindia.com/api/fiidiiTradeReact',
            timeout=8
        )
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")

        data = resp.json()
        result = {}

        for item in data:
            cat = str(item.get('category', '')).upper()
            # NSE returns values in crores directly
            try:
                buy  = float(str(item.get('buyValue',  '0')).replace(',', ''))
                sell = float(str(item.get('sellValue', '0')).replace(',', ''))
                net  = float(str(item.get('netValue',  str(buy - sell))).replace(',', ''))
            except (ValueError, TypeError):
                continue

            if 'FPI' in cat or 'FII' in cat:
                result.update({
                    'fii_buy_cr':  round(buy,  2),
                    'fii_sell_cr': round(sell, 2),
                    'fii_net_cr':  round(net,  2),
                    'fii_date':    item.get('date', ''),
                })
            elif 'DII' in cat:
                result.update({
                    'dii_buy_cr':  round(buy,  2),
                    'dii_sell_cr': round(sell, 2),
                    'dii_net_cr':  round(net,  2),
                })

        if result:
            log_system_event("data_fetcher", "INFO",
                             f"FII net: ₹{result.get('fii_net_cr', 0):,.0f} Cr | "
                             f"DII net: ₹{result.get('dii_net_cr', 0):,.0f} Cr")
        return result

    except Exception as e:
        log_system_event("data_fetcher", "WARNING", f"FII/DII fetch failed: {e}")
        return {}


def store_fii_dii(fii_data: dict, date_str: str = None):
    """Persist FII/DII numbers into the macro_data table."""
    if not fii_data:
        return
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO macro_data (date, fii_net_cr, dii_net_cr)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                fii_net_cr = excluded.fii_net_cr,
                dii_net_cr = excluded.dii_net_cr
        """, (
            date_str,
            fii_data.get('fii_net_cr'),
            fii_data.get('dii_net_cr'),
        ))
        conn.commit()
    except Exception as e:
        log_system_event("data_fetcher", "WARNING", f"store_fii_dii failed: {e}")
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# BULK / BLOCK DEALS  —  hidden institutional footprint
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_bulk_block_deals() -> list:
    """
    Fetch today's bulk and block deals from NSE.
    These reveal large institutional / operator transactions not visible
    in regular price data — a key 'hidden opportunity' signal.
    Returns list of deal dicts.
    """
    if not HAS_REQUESTS:
        return []

    # NSE geo-blocks cloud IPs — skip fast instead of hanging on timeouts.
    if not nse_reachable():
        log_system_event("data_fetcher", "INFO", "NSE unreachable — skipping bulk/block deals")
        return []

    deals = []
    try:
        session = _nse_session()

        for endpoint, deal_type in [
            ('https://www.nseindia.com/api/bulkdeals', 'BULK'),
            ('https://www.nseindia.com/api/blockdeals', 'BLOCK'),
        ]:
            try:
                resp = session.get(endpoint, timeout=8)
                if resp.status_code != 200:
                    continue
                raw = resp.json()
                # NSE wraps data in a 'data' key
                rows = raw if isinstance(raw, list) else raw.get('data', [])
                for row in rows:
                    symbol = (
                        row.get('symbol') or row.get('Symbol') or
                        row.get('scripCode') or ''
                    ).strip().upper()
                    # Strip .NS suffix if present
                    if symbol.endswith('.NS'):
                        symbol = symbol[:-3]

                    deals.append({
                        'type':      deal_type,
                        'symbol':    symbol,
                        'client':    row.get('clientName') or row.get('client') or 'Unknown',
                        'buy_sell':  (row.get('buySell') or row.get('BD_DT_DATE') or 'BUY').upper(),
                        'quantity':  int(float(row.get('quantityTraded') or row.get('qty') or 0)),
                        'price':     float(row.get('tradePrice') or row.get('price') or 0),
                        'value_cr':  round(
                            float(row.get('quantityTraded') or 0) *
                            float(row.get('tradePrice') or 0) / 1e7, 2
                        ),
                        'date':      row.get('date') or row.get('BD_DT_DATE') or
                                     datetime.now().strftime('%d-%b-%Y'),
                    })
            except Exception as e:
                log_system_event("data_fetcher", "WARNING",
                                 f"{deal_type} deals fetch failed: {e}")

        log_system_event("data_fetcher", "INFO",
                         f"Fetched {len(deals)} bulk/block deal records")
    except Exception as e:
        log_system_event("data_fetcher", "WARNING", f"fetch_bulk_block_deals failed: {e}")

    return deals


def store_bulk_block_deals(deals: list):
    """Store deals in the bulk_deals table."""
    if not deals:
        return
    conn = get_connection()
    try:
        for d in deals:
            conn.execute("""
                INSERT OR IGNORE INTO bulk_deals
                (deal_type, symbol, client_name, buy_sell, quantity, price, value_cr, deal_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                d['type'], d['symbol'], d['client'], d['buy_sell'],
                d['quantity'], d['price'], d['value_cr'], d['date'],
            ))
        conn.commit()
    except Exception as e:
        log_system_event("data_fetcher", "WARNING", f"store_bulk_block_deals failed: {e}")
    finally:
        conn.close()


def get_recent_bulk_deals(days: int = 3, min_value_cr: float = 5.0) -> list:
    """
    Return recent significant bulk/block deals (value ≥ min_value_cr crores).
    Useful for 'hidden opportunity' detection.
    """
    conn = get_connection()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM bulk_deals
            WHERE value_cr >= ? AND fetched_date >= ?
            ORDER BY value_cr DESC
            LIMIT 50
        """, (min_value_cr, cutoff))
        rows = [dict(r) for r in cursor.fetchall()]
    except Exception:
        rows = []
    finally:
        conn.close()
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# CORPORATE ANNOUNCEMENTS  —  NSE BSE RSS feeds
# ═══════════════════════════════════════════════════════════════════════════════

_ANNOUNCEMENT_FEEDS = [
    {
        'name': 'NSE Corporate',
        'url':  'https://www.nseindia.com/rss/corp-announcements.xml',
    },
    {
        'name': 'BSE Corporate',
        'url':  'https://www.bseindia.com/Rss/RssFeeds.aspx?type=CAnn',
    },
    {
        'name': 'Economic Times Results',
        'url':  'https://economictimes.indiatimes.com/markets/earnings/rssfeeds/2143429.cms',
    },
]

# High-value announcement keywords
_HIGH_IMPACT_WORDS = {
    'results', 'earnings', 'dividend', 'bonus', 'split', 'buyback',
    'merger', 'acquisition', 'order', 'contract', 'approval', 'rating',
    'fund raise', 'qip', 'fpo', 'ipo', 'stake', 'debt', 'promoter',
    'board meeting', 'agm', 'egm', 'rbi', 'sebi', 'fda', 'usfda',
}


def fetch_corporate_announcements() -> list:
    """
    Fetch corporate announcements from NSE/BSE RSS feeds.
    Returns list of announcement dicts.
    """
    if not HAS_FEEDPARSER:
        return []

    announcements = []
    for feed_cfg in _ANNOUNCEMENT_FEEDS:
        try:
            feed = feedparser.parse(feed_cfg['url'])
            for entry in feed.entries[:40]:
                title   = getattr(entry, 'title', '').strip()
                summary = getattr(entry, 'summary', '').strip()

                # Parse date
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub = datetime(*entry.published_parsed[:6]).strftime('%Y-%m-%d %H:%M')
                else:
                    pub = datetime.now().strftime('%Y-%m-%d %H:%M')

                # Score impact
                text_lower = (title + ' ' + summary).lower()
                impact_count = sum(1 for kw in _HIGH_IMPACT_WORDS if kw in text_lower)
                impact = 'HIGH' if impact_count >= 2 else ('MEDIUM' if impact_count == 1 else 'LOW')

                announcements.append({
                    'title':    title,
                    'summary':  summary[:300],
                    'source':   feed_cfg['name'],
                    'url':      getattr(entry, 'link', ''),
                    'date':     pub,
                    'impact':   impact,
                })
        except Exception as e:
            log_system_event("data_fetcher", "WARNING",
                             f"Announcement feed {feed_cfg['name']} failed: {e}")

    log_system_event("data_fetcher", "INFO",
                     f"Fetched {len(announcements)} corporate announcements")
    return announcements


if __name__ == "__main__":
    from database import init_database
    init_database()
    run_data_pipeline()

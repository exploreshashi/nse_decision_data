"""
Screener.in Integration
Fetches live fundamental data using the user's premium Screener.in account.
Data is cached in the fundamentals table (7-day TTL) to respect rate limits.
"""

import re
import sys
import os
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules.database import get_connection, log_system_event

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

BASE_URL    = "https://www.screener.in"
LOGIN_URL   = f"{BASE_URL}/login/"
CACHE_DAYS  = 7          # Re-scrape only if data older than this
REQUEST_GAP = 1.5        # Seconds between company page requests

# ── Company name / slug overrides (when NSE symbol ≠ Screener slug) ──────────
SLUG_OVERRIDES = {
    "M&M":       "M-and-M",
    "BAJAJ-AUTO":"BAJAJ-AUTO",
    "MCDOWELL-N":"MCDOWELL-N",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Session management
# ═══════════════════════════════════════════════════════════════════════════════

_session: "requests.Session | None" = None


def _get_session(email: str, password: str) -> "requests.Session | None":
    global _session
    if _session is not None:
        return _session

    if not HAS_DEPS:
        log_system_event("screener", "ERROR", "requests/bs4 not installed")
        return None

    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": BASE_URL,
    })

    try:
        # Step 1: GET login page → extract CSRF token
        resp = s.get(LOGIN_URL, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        csrf_input = soup.find("input", {"name": "csrfmiddlewaretoken"})
        if not csrf_input:
            log_system_event("screener", "ERROR", "CSRF token not found on login page")
            return None
        csrf = csrf_input["value"]

        # Step 2: POST credentials
        login_resp = s.post(LOGIN_URL, data={
            "csrfmiddlewaretoken": csrf,
            "username": email,
            "password": password,
            "next": "/",
        }, timeout=15)

        # Screener redirects to / on success
        if "Invalid" in login_resp.text or login_resp.url == LOGIN_URL:
            log_system_event("screener", "ERROR",
                             "Screener.in login failed — check credentials")
            return None

        _session = s
        log_system_event("screener", "INFO", "Screener.in login successful")
        return s

    except Exception as e:
        log_system_event("screener", "ERROR", f"Screener.in login exception: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# HTML parsing helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _clean_number(text: str) -> float | None:
    """Strip units/commas and return float, or None."""
    if not text:
        return None
    text = text.strip()
    # Remove known non-numeric units but keep decimal points
    text = re.sub(r"[₹%,\s]", "", text)   # strip %, commas, spaces, rupee sign
    text = re.sub(r"(?i)cr\.?", "", text)  # strip "Cr" / "cr." unit
    text = text.split("/")[0].strip()      # "1200 / 800" → "1200"
    try:
        return float(text)
    except ValueError:
        return None


def _parse_top_ratios(soup: "BeautifulSoup") -> dict:
    """Parse the #top-ratios <ul> block."""
    out = {}
    ul = soup.find("ul", id="top-ratios")
    if not ul:
        return out

    for li in ul.find_all("li"):
        name_span  = li.find("span", class_="name")
        value_span = li.find("span", class_="number")
        if not (name_span and value_span):
            continue
        name  = name_span.get_text(strip=True)
        value = value_span.get_text(strip=True)

        key_map = {
            "Market Cap":     "market_cap_cr",
            "Current Price":  "current_price",
            "Stock P/E":      "pe_ratio",
            "Book Value":     "book_value",
            "Dividend Yield": "dividend_yield",
            "ROCE":           "roce",
            "ROE":            "roe",
            "Face Value":     "face_value",
        }
        for pattern, db_key in key_map.items():
            if pattern.lower() in name.lower():
                out[db_key] = _clean_number(value)
                break

    return out


def _parse_shareholding(soup: "BeautifulSoup") -> dict:
    """
    Parse the latest-quarter shareholding figures.
    Returns promoter%, FII%, DII%.
    """
    out = {}
    section = soup.find("section", id="shareholding")
    if not section:
        return out

    table = section.find("table")
    if not table:
        return out

    rows = table.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            cells = row.find_all("th")
        if len(cells) < 2:
            continue

        label = cells[0].get_text(strip=True).lower()
        # Latest quarter is the last td (rightmost)
        value_cells = row.find_all("td")
        if len(value_cells) < 2:
            continue
        # Last cell = most recent quarter
        val = _clean_number(value_cells[-1].get_text(strip=True))
        if val is None:
            continue

        if "promoter" in label:
            out["promoter_holding"] = val
        elif "fii" in label or "fpi" in label or "foreign" in label:
            out["fii_holding"] = val
        elif "dii" in label or "domestic" in label:
            out["dii_holding"] = val

    return out


def _parse_growth_rates(soup: "BeautifulSoup") -> dict:
    """
    Parse 'Compounded Growth Rates' tables inside #profit-loss section.
    Returns revenue_growth_yoy, profit_growth_yoy (3-year CAGRs).
    """
    out = {}
    section = soup.find("section", id="profit-loss")
    if not section:
        return out

    tables = section.find_all("table")
    for table in tables[1:]:   # skip the main P&L table (index 0)
        rows = table.find_all("tr")
        if not rows:
            continue
        header = rows[0].get_text(strip=True).lower()
        for row in rows[1:]:
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            period = cells[0].get_text(strip=True).lower()
            if "3 year" not in period and period != "3 years:":
                continue
            val = _clean_number(cells[1].get_text(strip=True))
            if val is None:
                continue
            if "sales" in header or "revenue" in header:
                out["revenue_growth_yoy"] = val
            elif "profit" in header:
                out["profit_growth_yoy"] = val

    return out


def _parse_key_metrics(soup: "BeautifulSoup") -> dict:
    """
    Parse OPM from #profit-loss table and D/E from #balance-sheet.
    """
    out = {}

    # OPM % from P&L table
    pl_sec = soup.find("section", id="profit-loss")
    if pl_sec:
        table = pl_sec.find("table")
        if table:
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if not cells:
                    continue
                label = cells[0].get_text(strip=True).lower()
                if "opm" in label:
                    val = _clean_number(cells[-1].get_text(strip=True))
                    if val is not None:
                        out["operating_margin"] = val

    # D/E from balance sheet: Borrowings / (Equity Capital + Reserves)
    bs_sec = soup.find("section", id="balance-sheet")
    if bs_sec:
        table = bs_sec.find("table")
        if table:
            borrowings = equity = reserves = None
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"])
                if not cells:
                    continue
                label = cells[0].get_text(strip=True).lower()
                last  = _clean_number(cells[-1].get_text(strip=True)) if len(cells) > 1 else None
                if "borrowing" in label:
                    borrowings = last
                elif label.startswith("equity capital"):
                    equity = last
                elif label.startswith("reserves"):
                    reserves = last
            if borrowings is not None and equity is not None and reserves is not None:
                net_worth = equity + reserves
                if net_worth > 0:
                    out["debt_equity"] = round(borrowings / net_worth, 2)

    return out



def _parse_sector(soup: "BeautifulSoup") -> str:
    """Extract sector from the Screener.in company page."""
    # Screener renders <a title="Broad Sector">Information Technology</a>
    a = soup.find("a", title="Broad Sector")
    if a:
        return a.get_text(strip=True)
    # Fallback: specific sector link
    a = soup.find("a", title="Sector")
    if a:
        return a.get_text(strip=True)
    return "Unknown"


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_company_data(symbol: str, email: str, password: str) -> dict | None:
    """
    Scrape one company's fundamental data from Screener.in.
    Returns merged dict of all parsed fields, or None on failure.
    """
    s = _get_session(email, password)
    if s is None:
        return None

    slug = SLUG_OVERRIDES.get(symbol, symbol)

    for variant in [f"/company/{slug}/consolidated/", f"/company/{slug}/"]:
        try:
            url  = BASE_URL + variant
            resp = s.get(url, timeout=15)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            data = {}
            data.update(_parse_top_ratios(soup))
            data.update(_parse_shareholding(soup))
            data.update(_parse_growth_rates(soup))
            data.update(_parse_key_metrics(soup))

            # Sector
            data["sector"] = _parse_sector(soup)

            # Promoter pledge — not always on main page; mark as 0 if missing
            data.setdefault("promoter_pledge", 0.0)

            log_system_event("screener", "INFO",
                             f"Scraped {symbol}: ROE={data.get('roe')} "
                             f"D/E={data.get('debt_equity')} "
                             f"Promoter={data.get('promoter_holding')}%")
            return data

        except Exception as e:
            log_system_event("screener", "WARNING",
                             f"Screener fetch {symbol} ({variant}): {e}")
            continue

    return None


def _is_cached(symbol: str) -> bool:
    """Return True if fresh data (< CACHE_DAYS) exists in DB."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT last_updated FROM fundamentals WHERE symbol = ?", (symbol,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row or not row["last_updated"]:
        return False
    try:
        updated = datetime.strptime(row["last_updated"], "%Y-%m-%d")
        return (datetime.now() - updated).days < CACHE_DAYS
    except Exception:
        return False


def _store_to_db(symbol: str, data: dict):
    """Persist scraped fundamental data into the fundamentals table."""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        conn.execute("""
            INSERT OR REPLACE INTO fundamentals
            (symbol, market_cap_cr, pe_ratio, roe, roce, debt_equity,
             promoter_holding, promoter_pledge, fii_holding, dii_holding,
             revenue_growth_yoy, profit_growth_yoy, operating_margin,
             dividend_yield, sector, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            symbol,
            data.get("market_cap_cr"),
            data.get("pe_ratio"),
            data.get("roe"),
            data.get("roce"),
            data.get("debt_equity"),
            data.get("promoter_holding"),
            data.get("promoter_pledge", 0),
            data.get("fii_holding"),
            data.get("dii_holding"),
            data.get("revenue_growth_yoy"),
            data.get("profit_growth_yoy"),
            data.get("operating_margin"),
            data.get("dividend_yield"),
            data.get("sector", "Unknown"),
            today,
        ))
        conn.commit()
    except Exception as e:
        log_system_event("screener", "WARNING", f"DB store {symbol}: {e}")
    finally:
        conn.close()


def refresh_fundamentals(symbols: list, email: str, password: str,
                         force: bool = False) -> dict:
    """
    Scrape and cache fundamentals for a list of symbols.
    Skips symbols with fresh cached data unless force=True.

    Returns: {"fetched": n, "cached": n, "failed": [symbols]}
    """
    fetched = 0
    cached  = 0
    failed  = []

    for symbol in symbols:
        if not force and _is_cached(symbol):
            cached += 1
            continue

        data = fetch_company_data(symbol, email, password)
        if data:
            _store_to_db(symbol, data)
            fetched += 1
        else:
            failed.append(symbol)

        time.sleep(REQUEST_GAP)   # Respect rate limit

    log_system_event("screener", "INFO",
                     f"Screener refresh: {fetched} fetched, {cached} cached, "
                     f"{len(failed)} failed")
    return {"fetched": fetched, "cached": cached, "failed": failed}


def load_from_db(symbol: str) -> dict | None:
    """Load cached fundamental data from the DB. Returns None if missing."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM fundamentals WHERE symbol = ?", (symbol,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    return d if d.get("roe") is not None else None

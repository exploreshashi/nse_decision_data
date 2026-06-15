"""
Fundamental Filter Module
Scores stocks on financial quality (0-100) and applies hard disqualifiers.

Data priority:
  1. Live Screener.in data (cached in DB, refreshed weekly)
  2. Static curated snapshot (fallback for uncached symbols)
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    MIN_ROE, MAX_DEBT_EQUITY, HARD_MAX_DEBT_EQUITY,
    MIN_PROMOTER_HOLDING, MAX_PROMOTER_PLEDGE, HARD_MAX_PROMOTER_PLEDGE,
    MIN_INSTITUTIONAL_HOLDING, MIN_REVENUE_GROWTH, MIN_PROFIT_GROWTH
)
from modules.database import get_connection, log_system_event


def _live_data(symbol: str) -> dict | None:
    """
    Return live fundamental data from DB (scraped from Screener.in).
    Maps DB columns → the same short-key dict used by scoring.
    Returns None if no data or data is None for critical fields.
    """
    try:
        from modules.screener_fetcher import load_from_db
        row = load_from_db(symbol)
        if not row:
            return None
        # Map DB columns to scoring keys
        inst = (row.get("fii_holding") or 0) + (row.get("dii_holding") or 0)
        return {
            "roe":    row.get("roe")    or 0,
            "de":     row.get("debt_equity") or 0,
            "ph":     row.get("promoter_holding") or 0,
            "pp":     row.get("promoter_pledge")  or 0,
            "inst":   inst,
            "rg":     row.get("revenue_growth_yoy") or 0,
            "pg":     row.get("profit_growth_yoy")  or 0,
            "om":     row.get("operating_margin")   or 0,
            "sector": row.get("sector") or "Unknown",
            "source": "screener_live",
        }
    except Exception:
        return None


# ── Curated fundamental data for top NSE stocks ──────────────────────────────
# This is a snapshot. In production, refresh quarterly from Screener.in.
# Data approximate as of Q3 FY25. Format:
# symbol: {roe, debt_equity, promoter_holding, promoter_pledge, fii+dii,
#          revenue_growth_yoy, profit_growth_yoy, operating_margin, sector}

FUNDAMENTAL_DATA = {
    # IT
    "TCS":       {"roe": 48, "de": 0.1, "ph": 72, "pp": 0, "inst": 22, "rg": 8, "pg": 10, "om": 25, "sector": "IT"},
    "INFY":      {"roe": 32, "de": 0.1, "ph": 15, "pp": 0, "inst": 55, "rg": 6, "pg": 8, "om": 24, "sector": "IT"},
    "HCLTECH":   {"roe": 24, "de": 0.1, "ph": 61, "pp": 0, "inst": 30, "rg": 7, "pg": 10, "om": 20, "sector": "IT"},
    "WIPRO":     {"roe": 15, "de": 0.2, "ph": 73, "pp": 0, "inst": 15, "rg": 1, "pg": -5, "om": 16, "sector": "IT"},
    "TECHM":     {"roe": 14, "de": 0.1, "ph": 35, "pp": 0, "inst": 40, "rg": 3, "pg": 25, "om": 14, "sector": "IT"},
    "LTIM":      {"roe": 28, "de": 0.1, "ph": 74, "pp": 0, "inst": 17, "rg": 6, "pg": 12, "om": 18, "sector": "IT"},
    "PERSISTENT":{"roe": 25, "de": 0.1, "ph": 31, "pp": 0, "inst": 40, "rg": 18, "pg": 30, "om": 16, "sector": "IT"},
    "COFORGE":   {"roe": 25, "de": 0.2, "ph": 40, "pp": 0, "inst": 38, "rg": 20, "pg": 25, "om": 15, "sector": "IT"},
    "MPHASIS":   {"roe": 22, "de": 0.1, "ph": 56, "pp": 0, "inst": 28, "rg": 5, "pg": 8, "om": 16, "sector": "IT"},
    "LTTS":      {"roe": 28, "de": 0.1, "ph": 74, "pp": 0, "inst": 16, "rg": 15, "pg": 20, "om": 18, "sector": "IT"},
    "TATAELXSI": {"roe": 35, "de": 0.0, "ph": 44, "pp": 0, "inst": 25, "rg": 8, "pg": 10, "om": 26, "sector": "IT"},

    # Banking
    "HDFCBANK":  {"roe": 16, "de": 8.0, "ph": 26, "pp": 0, "inst": 60, "rg": 25, "pg": 35, "om": 40, "sector": "Banking"},
    "ICICIBANK": {"roe": 18, "de": 7.0, "ph": 0, "pp": 0, "inst": 65, "rg": 25, "pg": 30, "om": 38, "sector": "Banking"},
    "KOTAKBANK": {"roe": 14, "de": 7.5, "ph": 26, "pp": 0, "inst": 55, "rg": 18, "pg": 20, "om": 35, "sector": "Banking"},
    "AXISBANK":  {"roe": 16, "de": 8.0, "ph": 8, "pp": 0, "inst": 60, "rg": 22, "pg": 40, "om": 32, "sector": "Banking"},
    "SBIN":      {"roe": 17, "de": 12, "ph": 57, "pp": 0, "inst": 25, "rg": 15, "pg": 25, "om": 25, "sector": "Banking"},
    "INDUSINDBK":{"roe": 12, "de": 9.0, "ph": 16, "pp": 0, "inst": 55, "rg": 12, "pg": 10, "om": 28, "sector": "Banking"},
    "BANKBARODA":{"roe": 14, "de": 12, "ph": 64, "pp": 0, "inst": 22, "rg": 15, "pg": 30, "om": 22, "sector": "Banking"},
    "FEDERALBNK":{"roe": 13, "de": 10, "ph": 0, "pp": 0, "inst": 45, "rg": 20, "pg": 25, "om": 22, "sector": "Banking"},
    "IDFCFIRSTB":{"roe": 10, "de": 9.0, "ph": 37, "pp": 0, "inst": 40, "rg": 25, "pg": 35, "om": 15, "sector": "Banking"},

    # Conglomerates
    "RELIANCE":  {"roe": 10, "de": 0.4, "ph": 50, "pp": 0, "inst": 35, "rg": 10, "pg": 8, "om": 16, "sector": "Conglomerate"},
    "LT":        {"roe": 14, "de": 0.8, "ph": 0, "pp": 0, "inst": 55, "rg": 18, "pg": 20, "om": 12, "sector": "Infrastructure"},
    "ITC":       {"roe": 28, "de": 0.0, "ph": 0, "pp": 0, "inst": 50, "rg": 8, "pg": 10, "om": 35, "sector": "FMCG"},
    "ADANIENT":  {"roe": 12, "de": 1.0, "ph": 73, "pp": 5, "inst": 20, "rg": 30, "pg": 40, "om": 10, "sector": "Conglomerate"},

    # Auto
    "TATAMOTORS":{"roe": 20, "de": 0.8, "ph": 46, "pp": 0, "inst": 30, "rg": 25, "pg": 50, "om": 12, "sector": "Auto"},
    "MARUTI":    {"roe": 18, "de": 0.0, "ph": 56, "pp": 0, "inst": 32, "rg": 15, "pg": 25, "om": 12, "sector": "Auto"},
    "M&M":       {"roe": 18, "de": 0.3, "ph": 19, "pp": 0, "inst": 50, "rg": 20, "pg": 35, "om": 16, "sector": "Auto"},
    "BAJAJ-AUTO":{"roe": 25, "de": 0.0, "ph": 55, "pp": 0, "inst": 25, "rg": 18, "pg": 22, "om": 20, "sector": "Auto"},
    "EICHERMOT": {"roe": 25, "de": 0.0, "ph": 49, "pp": 0, "inst": 35, "rg": 10, "pg": 15, "om": 28, "sector": "Auto"},
    "HEROMOTOCO":{"roe": 22, "de": 0.0, "ph": 35, "pp": 0, "inst": 40, "rg": 12, "pg": 18, "om": 14, "sector": "Auto"},
    "TVSMOTOR":  {"roe": 28, "de": 0.3, "ph": 50, "pp": 0, "inst": 25, "rg": 20, "pg": 30, "om": 10, "sector": "Auto"},
    "ASHOKLEY":  {"roe": 18, "de": 0.3, "ph": 51, "pp": 0, "inst": 30, "rg": 8, "pg": 15, "om": 10, "sector": "Auto"},

    # Pharma
    "SUNPHARMA": {"roe": 15, "de": 0.2, "ph": 54, "pp": 0, "inst": 30, "rg": 12, "pg": 20, "om": 22, "sector": "Pharma"},
    "DRREDDY":   {"roe": 18, "de": 0.1, "ph": 27, "pp": 0, "inst": 50, "rg": 14, "pg": 25, "om": 25, "sector": "Pharma"},
    "CIPLA":     {"roe": 15, "de": 0.1, "ph": 34, "pp": 0, "inst": 45, "rg": 10, "pg": 30, "om": 22, "sector": "Pharma"},
    "DIVISLAB":  {"roe": 18, "de": 0.0, "ph": 52, "pp": 0, "inst": 35, "rg": 15, "pg": 25, "om": 30, "sector": "Pharma"},
    "LUPIN":     {"roe": 16, "de": 0.2, "ph": 47, "pp": 0, "inst": 30, "rg": 18, "pg": 35, "om": 18, "sector": "Pharma"},
    "AUROPHARMA":{"roe": 14, "de": 0.3, "ph": 52, "pp": 2, "inst": 30, "rg": 10, "pg": 15, "om": 16, "sector": "Pharma"},

    # FMCG
    "HINDUNILVR":{"roe": 40, "de": 0.0, "ph": 62, "pp": 0, "inst": 30, "rg": 4, "pg": 5, "om": 24, "sector": "FMCG"},
    "NESTLEIND": {"roe": 95, "de": 0.1, "ph": 62, "pp": 0, "inst": 18, "rg": 8, "pg": 10, "om": 22, "sector": "FMCG"},
    "BRITANNIA": {"roe": 55, "de": 0.5, "ph": 51, "pp": 0, "inst": 25, "rg": 6, "pg": 8, "om": 18, "sector": "FMCG"},
    "DABUR":     {"roe": 22, "de": 0.1, "ph": 67, "pp": 0, "inst": 20, "rg": 5, "pg": 8, "om": 20, "sector": "FMCG"},
    "COLPAL":    {"roe": 65, "de": 0.2, "ph": 51, "pp": 0, "inst": 25, "rg": 8, "pg": 12, "om": 30, "sector": "FMCG"},
    "GODREJCP":  {"roe": 22, "de": 0.3, "ph": 63, "pp": 0, "inst": 20, "rg": 5, "pg": 10, "om": 22, "sector": "FMCG"},
    "TATACONSUM":{"roe": 8, "de": 0.2, "ph": 35, "pp": 0, "inst": 40, "rg": 12, "pg": 15, "om": 14, "sector": "FMCG"},

    # Metals
    "TATASTEEL": {"roe": 8, "de": 0.8, "ph": 33, "pp": 0, "inst": 30, "rg": -5, "pg": -20, "om": 8, "sector": "Metals"},
    "JSWSTEEL":  {"roe": 15, "de": 0.7, "ph": 45, "pp": 3, "inst": 25, "rg": 10, "pg": 20, "om": 16, "sector": "Metals"},
    "HINDALCO":  {"roe": 12, "de": 0.5, "ph": 35, "pp": 0, "inst": 40, "rg": 8, "pg": 15, "om": 12, "sector": "Metals"},
    "VEDL":      {"roe": 22, "de": 0.8, "ph": 62, "pp": 5, "inst": 18, "rg": 15, "pg": 40, "om": 25, "sector": "Metals"},
    "SAIL":      {"roe": 5, "de": 0.6, "ph": 65, "pp": 0, "inst": 15, "rg": -8, "pg": -30, "om": 6, "sector": "Metals"},
    "NMDC":      {"roe": 20, "de": 0.1, "ph": 60, "pp": 0, "inst": 15, "rg": 10, "pg": 15, "om": 40, "sector": "Metals"},
    "JINDALSTEL":{"roe": 15, "de": 0.5, "ph": 61, "pp": 0, "inst": 20, "rg": 12, "pg": 20, "om": 18, "sector": "Metals"},

    # Energy
    "NTPC":      {"roe": 12, "de": 1.2, "ph": 51, "pp": 0, "inst": 30, "rg": 8, "pg": 12, "om": 30, "sector": "Energy"},
    "POWERGRID": {"roe": 18, "de": 1.5, "ph": 51, "pp": 0, "inst": 28, "rg": 6, "pg": 10, "om": 85, "sector": "Energy"},
    "ONGC":      {"roe": 12, "de": 0.4, "ph": 58, "pp": 0, "inst": 20, "rg": 5, "pg": -10, "om": 20, "sector": "Energy"},
    "BPCL":      {"roe": 22, "de": 0.6, "ph": 53, "pp": 0, "inst": 25, "rg": 10, "pg": 30, "om": 5, "sector": "Energy"},
    "COALINDIA": {"roe": 52, "de": 0.1, "ph": 63, "pp": 0, "inst": 20, "rg": 5, "pg": 8, "om": 30, "sector": "Energy"},
    "TATAPOWER": {"roe": 12, "de": 0.8, "ph": 47, "pp": 0, "inst": 28, "rg": 25, "pg": 30, "om": 15, "sector": "Energy"},

    # NBFC/Financial
    "BAJFINANCE":{"roe": 22, "de": 3.5, "ph": 56, "pp": 0, "inst": 25, "rg": 30, "pg": 25, "om": 50, "sector": "NBFC"},
    "BAJAJFINSV":{"roe": 15, "de": 0.5, "ph": 56, "pp": 0, "inst": 22, "rg": 20, "pg": 18, "om": 20, "sector": "NBFC"},
    "CHOLAFIN":  {"roe": 20, "de": 5.0, "ph": 52, "pp": 0, "inst": 28, "rg": 30, "pg": 25, "om": 35, "sector": "NBFC"},
    "MUTHOOTFIN":{"roe": 22, "de": 3.0, "ph": 73, "pp": 0, "inst": 18, "rg": 18, "pg": 20, "om": 45, "sector": "NBFC"},
    "SHRIRAMFIN":{"roe": 16, "de": 4.0, "ph": 26, "pp": 0, "inst": 50, "rg": 20, "pg": 22, "om": 30, "sector": "NBFC"},

    # Telecom
    "BHARTIARTL":{"roe": 15, "de": 1.5, "ph": 36, "pp": 0, "inst": 45, "rg": 18, "pg": 40, "om": 30, "sector": "Telecom"},

    # Consumer
    "TITAN":     {"roe": 30, "de": 0.3, "ph": 53, "pp": 0, "inst": 28, "rg": 20, "pg": 25, "om": 12, "sector": "Consumer"},
    "ASIANPAINT":{"roe": 28, "de": 0.2, "ph": 53, "pp": 0, "inst": 28, "rg": 5, "pg": 8, "om": 18, "sector": "Consumer"},
    "PIDILITIND":{"roe": 25, "de": 0.1, "ph": 70, "pp": 0, "inst": 20, "rg": 12, "pg": 15, "om": 22, "sector": "Consumer"},
    "HAVELLS":   {"roe": 22, "de": 0.1, "ph": 60, "pp": 0, "inst": 20, "rg": 15, "pg": 20, "om": 12, "sector": "Consumer"},
    "TRENT":     {"roe": 20, "de": 0.3, "ph": 37, "pp": 0, "inst": 35, "rg": 50, "pg": 80, "om": 14, "sector": "Retail"},
    "DMART":     {"roe": 14, "de": 0.0, "ph": 75, "pp": 0, "inst": 18, "rg": 18, "pg": 15, "om": 8, "sector": "Retail"},

    # Defence
    "HAL":       {"roe": 28, "de": 0.0, "ph": 72, "pp": 0, "inst": 12, "rg": 25, "pg": 30, "om": 25, "sector": "Defence"},
    "BEL":       {"roe": 25, "de": 0.0, "ph": 51, "pp": 0, "inst": 18, "rg": 30, "pg": 35, "om": 25, "sector": "Defence"},
    "BHEL":      {"roe": 8, "de": 0.3, "ph": 63, "pp": 0, "inst": 15, "rg": 15, "pg": 50, "om": 8, "sector": "Capital Goods"},

    # Real Estate
    "DLF":       {"roe": 8, "de": 0.2, "ph": 75, "pp": 0, "inst": 18, "rg": 20, "pg": 30, "om": 30, "sector": "Real Estate"},
    "GODREJPROP":{"roe": 10, "de": 0.5, "ph": 58, "pp": 0, "inst": 25, "rg": 30, "pg": 40, "om": 18, "sector": "Real Estate"},
    "OBEROIRLTY":{"roe": 12, "de": 0.2, "ph": 67, "pp": 0, "inst": 18, "rg": 25, "pg": 50, "om": 45, "sector": "Real Estate"},

    # Capital Goods
    "ABB":       {"roe": 22, "de": 0.1, "ph": 75, "pp": 0, "inst": 12, "rg": 20, "pg": 30, "om": 14, "sector": "Capital Goods"},
    "SIEMENS":   {"roe": 18, "de": 0.1, "ph": 75, "pp": 0, "inst": 10, "rg": 15, "pg": 25, "om": 12, "sector": "Capital Goods"},
    "CUMMINSIND":{"roe": 28, "de": 0.0, "ph": 51, "pp": 0, "inst": 25, "rg": 18, "pg": 30, "om": 18, "sector": "Capital Goods"},
    "POLYCAB":   {"roe": 22, "de": 0.1, "ph": 68, "pp": 0, "inst": 20, "rg": 25, "pg": 30, "om": 14, "sector": "Capital Goods"},
    "DIXON":     {"roe": 22, "de": 0.2, "ph": 34, "pp": 0, "inst": 35, "rg": 40, "pg": 50, "om": 5, "sector": "Electronics"},

    # Misc
    "ZOMATO":    {"roe": 5, "de": 0.0, "ph": 0, "pp": 0, "inst": 55, "rg": 55, "pg": 100, "om": 2, "sector": "Internet"},
    "IRCTC":     {"roe": 35, "de": 0.0, "ph": 62, "pp": 0, "inst": 15, "rg": 15, "pg": 20, "om": 45, "sector": "Travel"},
    "INDIGO":    {"roe": 45, "de": 1.5, "ph": 50, "pp": 0, "inst": 30, "rg": 25, "pg": 60, "om": 15, "sector": "Aviation"},
    "ULTRACEMCO":{"roe": 12, "de": 0.3, "ph": 60, "pp": 0, "inst": 22, "rg": 10, "pg": 15, "om": 18, "sector": "Cement"},
    "AMBUJACEM": {"roe": 10, "de": 0.1, "ph": 63, "pp": 0, "inst": 22, "rg": 8, "pg": 12, "om": 16, "sector": "Cement"},
    "GRASIM":    {"roe": 10, "de": 0.5, "ph": 44, "pp": 0, "inst": 30, "rg": 12, "pg": 15, "om": 14, "sector": "Diversified"},
    "SRF":       {"roe": 16, "de": 0.4, "ph": 50, "pp": 0, "inst": 28, "rg": 8, "pg": 10, "om": 18, "sector": "Chemicals"},
    "PIIND":     {"roe": 20, "de": 0.2, "ph": 46, "pp": 0, "inst": 30, "rg": 15, "pg": 20, "om": 22, "sector": "Chemicals"},
    "JUBLFOOD":  {"roe": 22, "de": 1.0, "ph": 42, "pp": 0, "inst": 30, "rg": 15, "pg": 20, "om": 15, "sector": "QSR"},
    "MOTHERSON": {"roe": 14, "de": 0.6, "ph": 68, "pp": 0, "inst": 18, "rg": 20, "pg": 30, "om": 8, "sector": "Auto Ancillary"},
}


def score_fundamental(symbol: str) -> dict:
    """
    Score a stock on fundamental quality (0-100).
    Data priority: live Screener.in → static snapshot.
    """
    # Try live data first
    data = _live_data(symbol)

    # Fall back to static snapshot
    if data is None:
        raw  = FUNDAMENTAL_DATA.get(symbol)
        if raw:
            data = dict(raw); data["source"] = "static"

    if data is None:
        return {
            'score': 50, 'disqualified': False,
            'reason': 'No fundamental data — neutral score (run Screener refresh)',
            'breakdown': {}, 'sector': 'Unknown', 'data': {},
        }

    # ── Hard Disqualifiers ────────────────────────────────────────────────
    # Skip debt/equity check for banks and NBFCs (naturally high D/E)
    is_financial = data['sector'] in ['Banking', 'NBFC']

    if not is_financial and data['de'] > HARD_MAX_DEBT_EQUITY:
        return {
            'score': 0, 'disqualified': True,
            'reason': f"Debt/Equity too high: {data['de']:.1f} (max {HARD_MAX_DEBT_EQUITY})",
            'sector': data['sector'], 'data': data
        }

    if data['pp'] > HARD_MAX_PROMOTER_PLEDGE:
        return {
            'score': 0, 'disqualified': True,
            'reason': f"Promoter pledge too high: {data['pp']}% (max {HARD_MAX_PROMOTER_PLEDGE}%)",
            'sector': data['sector'], 'data': data
        }

    # ── Scoring ───────────────────────────────────────────────────────────
    score = 0
    breakdown = {}

    # 1. Revenue growth > 10% YoY (15 pts)
    if data['rg'] >= MIN_REVENUE_GROWTH:
        pts = 15
        if data['rg'] >= 25: pts = 15
        elif data['rg'] >= 15: pts = 12
        else: pts = 8
        score += pts
        breakdown['revenue_growth'] = pts
    else:
        breakdown['revenue_growth'] = 0

    # 2. Profit growth > 15% YoY (15 pts)
    if data['pg'] >= MIN_PROFIT_GROWTH:
        pts = 15
        if data['pg'] >= 30: pts = 15
        elif data['pg'] >= 20: pts = 12
        else: pts = 8
        score += pts
        breakdown['profit_growth'] = pts
    elif data['pg'] > 0:
        score += 3
        breakdown['profit_growth'] = 3
    else:
        breakdown['profit_growth'] = 0

    # 3. ROE > 12% (10 pts)
    if data['roe'] >= MIN_ROE:
        pts = 10 if data['roe'] >= 20 else 7
        score += pts
        breakdown['roe'] = pts
    else:
        breakdown['roe'] = 0

    # 4. Debt/Equity < 1.0 (10 pts) — skip for financials
    if is_financial:
        score += 7  # Financials get moderate score here
        breakdown['debt_equity'] = 7
    elif data['de'] <= MAX_DEBT_EQUITY:
        pts = 10 if data['de'] <= 0.3 else 7
        score += pts
        breakdown['debt_equity'] = pts
    else:
        breakdown['debt_equity'] = 0

    # 5. Promoter holding > 40% (10 pts)
    if data['ph'] >= MIN_PROMOTER_HOLDING:
        pts = 10 if data['ph'] >= 55 else 7
        score += pts
        breakdown['promoter_holding'] = pts
    elif data['ph'] >= 25:
        score += 4
        breakdown['promoter_holding'] = 4
    else:
        # Some good companies have low promoter holding (e.g., widely held)
        if data['inst'] >= 50:
            score += 5  # Offset by high institutional holding
            breakdown['promoter_holding'] = 5
        else:
            breakdown['promoter_holding'] = 0

    # 6. Promoter pledge < 10% (10 pts)
    if data['pp'] <= MAX_PROMOTER_PLEDGE:
        pts = 10 if data['pp'] == 0 else 6
        score += pts
        breakdown['promoter_pledge'] = pts
    else:
        breakdown['promoter_pledge'] = 0

    # 7. Institutional holding > 25% (10 pts)
    if data['inst'] >= MIN_INSTITUTIONAL_HOLDING:
        pts = 10 if data['inst'] >= 40 else 7
        score += pts
        breakdown['institutional'] = pts
    else:
        score += 3
        breakdown['institutional'] = 3

    # 8. Operating margin stable/positive (10 pts)
    if data['om'] >= 20:
        score += 10
        breakdown['op_margin'] = 10
    elif data['om'] >= 12:
        score += 7
        breakdown['op_margin'] = 7
    elif data['om'] >= 5:
        score += 3
        breakdown['op_margin'] = 3
    else:
        breakdown['op_margin'] = 0

    # Cap at 100
    score = min(score, 100)

    return {
        'score': score,
        'disqualified': False,
        'reason': 'Passed fundamental filter',
        'breakdown': breakdown,
        'sector': data['sector'],
        'data_source': data.get('source', 'static'),
        'data': {
            'roe':             data['roe'],
            'debt_equity':     data['de'],
            'promoter_holding':data['ph'],
            'promoter_pledge': data['pp'],
            'fii_dii_holding': data['inst'],
            'revenue_growth':  data['rg'],
            'profit_growth':   data['pg'],
            'operating_margin':data['om'],
        }
    }


def get_stock_sector(symbol: str) -> str:
    """Get sector for a stock."""
    data = FUNDAMENTAL_DATA.get(symbol, {})
    return data.get('sector', 'Unknown')


def store_fundamentals():
    """Store fundamental data in database."""
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')

    for symbol, data in FUNDAMENTAL_DATA.items():
        try:
            cursor.execute("""
                INSERT OR REPLACE INTO fundamentals
                (symbol, roe, debt_equity, promoter_holding, promoter_pledge,
                 fii_holding, dii_holding, revenue_growth_yoy, profit_growth_yoy,
                 operating_margin, sector, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, data['roe'], data['de'], data['ph'], data['pp'],
                data['inst'] * 0.6, data['inst'] * 0.4,  # Rough split
                data['rg'], data['pg'], data['om'], data['sector'], today
            ))
        except Exception:
            continue

    conn.commit()
    conn.close()
